---
title: Troubleshooting Guide - Access and Sign-in
doc_type: troubleshooting
---

# Troubleshooting: Access and Sign-in Issues

## Symptom: "Your dashboard is locked"

A locked dashboard means the account status is `locked`, usually caused by
repeated failed sign-in attempts or a suspected credential compromise.

Steps:

1. Verify the requester is the account owner or an admin on the account.
2. Confirm the account status is `locked` (not `suspended`).
3. Unlock the dashboard. Unlocking transitions the account from locked back
   to active; it has no effect on active or suspended accounts.
4. Advise the customer to reset their password if the lock was caused by
   failed sign-in attempts.

A suspended account is a billing state, not a security state. Do not attempt
to unlock a suspended account — the customer must settle outstanding invoices
first, after which the account reactivates automatically.

## Symptom: password reset email never arrives

1. Check the address is the one registered on the account.
2. Ask the customer to check spam and to allowlist noreply@agentflow.ai.
3. Corporate mail gateways can delay delivery by up to 15 minutes.

## Symptom: SSO sign-in loops back to the login page

1. Confirm the account is on the Enterprise plan — SSO is Enterprise-only.
2. Verify the identity provider metadata has not expired.
3. Clock skew above 5 minutes between the IdP and AgentFlow breaks SAML
   assertions; check the IdP server time.
