"""Save a party note and resolve its guest references inside a claimed tool job."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import Connection, Engine

from moseby.contracts.party_details import CreatePartyDetailRequestPayload, PartyDetail
from moseby.db.errors import WriteConflict
from moseby.db.models.inference_requests import NewInferenceRequest
from moseby.db.models.party_details import (
    GuestReferences,
    NewPartyDetail,
    PartyDetailRow,
)
from moseby.db.models.request_deduplication import RequestKey
from moseby.db.operations import conversations
from moseby.db.pagination import PageRequest
from moseby.db.repositories import (
    guests,
    inference_requests,
    parties,
    party_details,
    request_deduplication,
)
from moseby.db.repositories._writes import require_found
from moseby.db.timestamps import to_datetime
from moseby.domain.enums import GuestReferenceStatus
from moseby.identifiers import (
    HotelId,
    InferenceRequestId,
    PartyId,
    ThreadRecordId,
    new_id,
)
from moseby.inference.errors import InferenceError
from moseby.inference.guest_references import (
    GuestCandidate,
    GuestReferenceDecision,
    prepare_request,
    resolve,
)
from moseby.inference.models.classification import (
    ClassificationOutput,
    ClassificationRequest,
)
from moseby.inference.models.common import InferenceResult
from moseby.inference.provider import InferenceProvider
from moseby.runtime.enums import InferencePurpose
from moseby.runtime.models.common import ErrorDetails
from moseby.runtime.models.thread_records import (
    ClassifierDecisionPayload,
    ClassifierDecisionStatus,
    InferenceRequestPayload,
    ThreadRecordKind,
)
from moseby.services.guests import READ_PERMISSION, WRITE_PERMISSION
from moseby.tools.definitions import ToolContext

from .tool_writes import claimed_write


class GuestReferenceErrorCode(StrEnum):
    FAILED = "GUEST_REFERENCE_ERROR_FAILED"


def classifier_decision_status(
    status: GuestReferenceStatus,
) -> ClassifierDecisionStatus:
    """Translate a settled note outcome into the corresponding thread-record status."""
    match status:
        case GuestReferenceStatus.RESOLVED:
            return ClassifierDecisionStatus.RESOLVED
        case GuestReferenceStatus.AMBIGUOUS:
            return ClassifierDecisionStatus.AMBIGUOUS
        case GuestReferenceStatus.FAILED:
            return ClassifierDecisionStatus.FAILED
        case _:
            raise ValueError("A pending note has no classification decision yet")


@dataclass(frozen=True)
class PendingReferences:
    note: PartyDetailRow
    request: ClassificationRequest
    inference_id: InferenceRequestId
    marker_id: ThreadRecordId
    candidates: list[GuestCandidate]


def to_contract(note: PartyDetailRow) -> PartyDetail:
    return PartyDetail.model_validate(
        note.model_dump(exclude={"updated_at"})
        | {"created_at": to_datetime(note.created_at)}
    )


@dataclass(frozen=True)
class GuestReferenceRecorder:
    engine: Engine
    provider: InferenceProvider
    provider_name: str
    model: str

    async def record(
        self, context: ToolContext, request: CreatePartyDetailRequestPayload
    ) -> PartyDetail:
        """Persist evidence first, call the classifier, then save its outcome under the claim."""
        prepared = self._prepare(context, request)
        if isinstance(prepared, PartyDetailRow):
            return to_contract(prepared)
        try:
            result = await self.provider.classify(prepared.request)
            decision = resolve(prepared.request, result.output)
        except BaseException as error:
            detail = ErrorDetails(
                code=error.code
                if isinstance(error, InferenceError)
                else GuestReferenceErrorCode.FAILED,
                message="The note was saved, but its guest references could not be determined.",
                details={"party_detail_id": prepared.note.id},
            )
            saved = self._finish(context, prepared, error=detail)
            if isinstance(error, (InferenceError, ValueError)):
                return to_contract(saved)
            raise
        return to_contract(
            self._finish(context, prepared, decision=decision, result=result)
        )

    def _write(
        self, context: ToolContext
    ) -> AbstractContextManager[tuple[Connection, int]]:
        return claimed_write(
            self.engine, context, permissions=(READ_PERMISSION, WRITE_PERMISSION)
        )

    def _candidates(
        self, connection: Connection, party_id: PartyId, hotel_id: HotelId
    ) -> list[GuestCandidate]:
        page = guests.find_all_by_party_id(
            connection, party_id, hotel_id=hotel_id, page=PageRequest(limit=100)
        )
        if page.next_cursor is not None:
            raise ValueError(
                "Guest-reference classification supports parties of up to 100 guests"
            )
        return [
            GuestCandidate.model_validate(
                row.model_dump(include=set(GuestCandidate.model_fields))
            )
            for row in page.items
        ]

    def _prepare(
        self, context: ToolContext, request: CreatePartyDetailRequestPayload
    ) -> PendingReferences | PartyDetailRow:
        actor = context.domain_context.staff_member_id
        hotel = context.domain_context.hotel_id
        with self._write(context) as (connection, now):
            # Check hotel ownership before accepting a command or reading guest details.
            if parties.find_by_id(connection, request.party_id, hotel_id=hotel) is None:
                raise ValueError(
                    "The party was not found in this hotel. Search for the guest and use their party ID."
                )
            key = RequestKey(
                actor_staff_member_id=actor,
                operation="party-details.create",
                request_id=context.request_id,
            )
            accepted = request_deduplication.accept(
                connection,
                key,
                {"hotel_id": hotel, "payload": request.model_dump(mode="json")},
                now=now,
            )
            if not accepted.created:
                # A repeated command reuses its note, including any unfinished classification.
                if accepted.request.response is None:
                    raise WriteConflict("The note request has no saved receipt")
                saved = require_found(
                    party_details.find_by_id(
                        connection,
                        accepted.request.response["detail_id"],
                        hotel_id=hotel,
                    )
                )
                if saved.reference_status == GuestReferenceStatus.PENDING:
                    raise WriteConflict(
                        f"Note {saved.id} is saved and its references are still pending"
                    )
                return saved

            # Freeze the candidate list used to interpret this particular note.
            candidates = self._candidates(connection, request.party_id, hotel)
            classification = prepare_request(request.text, candidates)
            used = inference_requests.token_usage(
                connection, context.run_id, creator_staff_member_id=actor
            )
            # Compare reported usage with the run's token limit before starting another call.
            if context.token_budget is None:
                raise WriteConflict("No token limit is configured for this run")
            if used is None:
                raise WriteConflict(
                    "Reported token usage is missing; classification cannot check the remaining budget"
                )
            if used >= context.token_budget:
                raise WriteConflict("The run has already reached its token limit")

            # Keep the evidence even if the subsequent provider call fails.
            note = party_details.create(
                connection,
                NewPartyDetail(id=new_id("party_detail"), **request.model_dump()),
                hotel_id=hotel,
                now=now,
            )
            inference_id = new_id("inference_request")
            # Save the exact request and link it to the tool call that supplied the note.
            inference_requests.prepare(
                connection,
                NewInferenceRequest(
                    id=inference_id,
                    thread_id=context.thread_context.thread_id,
                    run_id=context.run_id,
                    provider=self.provider_name,
                    model=self.model,
                    purpose=InferencePurpose.CLASSIFIER,
                    request=classification.model_dump(mode="json"),
                ),
                [context.source_record_id],
                creator_staff_member_id=actor,
                now=now,
            )
            marker = conversations.append(
                connection,
                context.thread_context.thread_id,
                ThreadRecordKind.INFERENCE_REQUEST,
                InferenceRequestPayload(inference_request_id=inference_id),
                actor=actor,
                now=now,
                run_id=context.run_id,
                source_record_id=context.source_record_id,
            )
            inference_requests.start(
                connection, inference_id, creator_staff_member_id=actor, now=now
            )
            # Commit a receipt so a retry can find the note without creating another one.
            request_deduplication.save_response(
                connection, key, {"detail_id": note.id}, now=now
            )
            return PendingReferences(
                note, classification, inference_id, marker.id, candidates
            )

    def _finish(
        self,
        context: ToolContext,
        pending: PendingReferences,
        *,
        decision: GuestReferenceDecision | None = None,
        result: InferenceResult[ClassificationOutput] | None = None,
        error: ErrorDetails | None = None,
    ) -> PartyDetailRow:
        """Save the inference outcome, references and decision record in one transaction."""
        actor = context.domain_context.staff_member_id
        hotel = context.domain_context.hotel_id
        with self._write(context) as (connection, now):
            # Accept references only while the guest information still matches the request.
            if error is not None:
                decision = GuestReferenceDecision(status=GuestReferenceStatus.FAILED)
            elif (
                self._candidates(connection, pending.note.party_id, hotel)
                != pending.candidates
            ):
                # Changed guest details make this answer unsafe to attach to guest IDs.
                decision = GuestReferenceDecision(status=GuestReferenceStatus.AMBIGUOUS)
            # Validate party membership and save the IDs alongside their resolution status.
            saved = party_details.save_references(
                connection,
                pending.note.id,
                GuestReferences(status=decision.status, guest_ids=decision.guest_ids),
                expected_updated_at=pending.note.updated_at,
                hotel_id=hotel,
                now=now,
            )
            # Retain the provider's response or failure with the original inference attempt.
            inference_requests.finish(
                connection,
                pending.inference_id,
                creator_staff_member_id=actor,
                now=now,
                response=result.model_dump(mode="json") if result is not None else None,
                error=error,
            )
            # Record the decision in the same transaction as the updated note.
            conversations.append(
                connection,
                context.thread_context.thread_id,
                ThreadRecordKind.CLASSIFIER_DECISION,
                ClassifierDecisionPayload(
                    inference_request_id=pending.inference_id,
                    input_record_ids=[context.source_record_id],
                    status=classifier_decision_status(decision.status),
                    error=error,
                    decision={
                        "party_detail_id": saved.id,
                        **decision.model_dump(mode="json"),
                    }
                    if error is None
                    else None,
                ),
                actor=actor,
                now=now,
                run_id=context.run_id,
                source_record_id=pending.marker_id,
            )
            return saved
