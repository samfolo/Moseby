---
first_committed: "2026-09-18T19:11:16+01:00"
first_commit: "84d33d6"
---

# Separating checkout from a booked stay

## Objective

Let staff prepare a booking without creating guests, taking payment or occupying
rooms too early. Keep an existing stay safe while a change is being arranged.

This was a proposed payment flow. The demo later deferred checkout and payment;
it creates confirmed stays without claiming that money has been collected.

## Thinking at this stage

- Checkout holds the proposed guest details, room choices and quote before the
  booking exists. Shopping and editing do not reserve rooms.
- A hold reserves capacity for a short time. Its expiry is different from the
  dates of the stay. Taking it must recheck availability in the same transaction.
- Freeze the choices and agreed price while held. Back out of the hold before
  editing; the revised choices must compete for capacity again.
- Catalogue prices may change afterwards. Keep the quoted amounts, currency and
  rate versions so we can explain what the guest agreed to.

### Proposed confirmation flow

1. Prepare the checkout and guest information.
2. Acquire a hold and freeze the quote.
3. Obtain staff approval, then ask the payment integration to collect payment.
4. When it reports success, check that the hold is still valid.
5. In one local transaction, consume the hold and create the booking, party,
   guests and room reservations.

The payment provider cannot join that local transaction. A payment can succeed
after a hold expires; that needs resolution, not silent reuse of released rooms.
A repeated payment result must not create another booking.

### Changing rooms

- Keep the original allocation until the replacement is secured.
- Agree any price adjustment, including a complimentary change, before committing it.
- Replace the allocation in one transaction. If the change fails, keep the old room.
- Keep the booking and party. A room change should not erase their notes or activities.
- We dropped `under_revision` and technical `error` as booking states. A proposed
  or failed change does not make the existing confirmed stay invalid.
- Cancelling the whole booking is different and remains final.

### Temporary guest details

Save only what is needed to resume or resolve checkout. We wanted abandoned
checkout details to expire and be deleted, but had not chosen the retention rule.
Deleting a checkout row would not also delete copies in conversations or logs.
Do not call deliberately saved checkout data “zero retention.”

## Questions left open at this stage

- Does one hold cover the whole selection, or does each item have its own hold?
- How long does it last? Roughly five minutes was suggested later.
- What happens if payment is still uncertain when the hold expires or staff cancel?
- How should extra payment or a refund work for a stay amendment?
- Which checkout details must remain while a payment outcome is being resolved?
- What happens when someone joins a party or leaves early?

These questions remain relevant to a future payment integration. They are not
extra steps required to run the current demo. See [follow-ups](11-follow-ups.md).
