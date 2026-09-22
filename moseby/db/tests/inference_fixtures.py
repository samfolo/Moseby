"""Scripted model replies for database-backed runtime tests."""

from moseby.inference.models.common import InferenceResult


class ScriptedProvider:
    def __init__(self, *replies, total_tokens=20):
        self.replies = iter(replies)
        self.requests = []
        self.total_tokens = total_tokens

    async def generate(self, request):
        self.requests.append(request)
        reply = next(self.replies)
        if callable(reply):
            reply = reply(request)
        if isinstance(reply, Exception):
            raise reply
        return InferenceResult(
            output=reply,
            request=request.model_dump(mode="json"),
            response={"choices": []},
            total_tokens=self.total_tokens,
        )
