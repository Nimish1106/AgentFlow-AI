---
title: Internal Runbook - Billing Disputes
doc_type: runbook
---

# Runbook: Handling Billing Disputes

Internal procedure for support agents working a billing dispute ticket.

## 1. Identify the invoice

Look up the invoice referenced by the customer. Confirm the invoice belongs to
the customer raising the ticket before discussing any details.

## 2. Classify the dispute

- **Duplicate charge** — the invoice payment status is `duplicate`. This is
  the only class eligible for automatic refund. Calculate the refund with the
  billing tools; the refund equals the full invoice amount.
- **Already refunded** — inform the customer of the refund date; refunds take
  5-7 business days to appear on their statement.
- **Pending payment** — nothing was charged yet; the authorization hold will
  clear automatically if the payment does not settle.
- **Disputed regular charge** — a paid invoice the customer believes is
  wrong. Never promise a refund. Escalate for policy review with an internal
  note summarising the customer's claim.

## 3. Record the outcome

Always add an internal note to the ticket recording the classification, the
invoice id, and the action taken. Every billing action is audit-logged; the
note must match the audit trail.

## 4. Escalation thresholds

Escalate to a human approver when:

- The refund amount exceeds 1000 USD.
- The customer disputes more than two invoices in 30 days.
- The invoice currency differs from the subscription currency.
