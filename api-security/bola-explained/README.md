---
title: Broken Object Level Authorization (BOLA) Explained
author: xexci
track: api-security
difficulty: beginner
language: en
description: A beginner-friendly explanation of Broken Object Level Authorization, how it occurs in APIs, and how developers can prevent it.
---

# Broken Object Level Authorization (BOLA) Explained

## Overview

**Broken Object Level Authorization (BOLA)** is an authorization vulnerability that occurs when an API fails to verify whether an authenticated user is authorized to access a specific object.

BOLA is closely related to **IDOR (Insecure Direct Object Reference)**, a commonly used term for cases where an application exposes object references without properly enforcing authorization. 

In an API, this can happen when an authenticated user is allowed to access an object they should not have access to.

For example, User A is authenticated and requests `/api/records/123`, which belongs to User B. If the API returns the record without checking whether User A is authorized to access it, the API has a BOLA vulnerability.

Authentication confirms who a user is, but it does not determine which specific objects they are authorized to access. 

If object-level authorization is not enforced on every relevant request, an attacker may be able to view, modify, or delete another user's data or object by changing object IDs, depending on what the API allows.

BOLA concerns authorization at the object level. If a user can access an API function that they should not have permission to use, such as an administrative function, that is a different authorization problem known as **Broken Function Level Authorization (BFLA)**.

## Prerequisites

Readers should have a basic understanding of:

* APIs and HTTP requests
* Authentication and authorization
* Basic concepts such as users, objects, and object IDs

## Steps

### Step 1: Identify the object

APIs often use identifiers to specify which object a user wants to access. For example:

`GET /api/records/123`

In this example, `123` is the identifier for a specific record. The API uses this identifier to determine which record to retrieve. 

Identifiers can also appear in query strings, request bodies, or headers, not just the URL path.

### Step 2: Check object-level authorization

The API must verify that the authenticated user is authorized to access the requested object.

For example:

`User A → GET /api/records/123`

Before returning the record, the API should check:

1. Who is the authenticated user?
2. Which record are they requesting?
3. Is that user authorized to access that specific record?

If the API only checks whether User A is authenticated and does not check if User A is authorized to access record `123`, the API may be vulnerable to BOLA.

The difference can be illustrated with the simplified pseudocode below:

# Vulnerable: no object-level authorization check
record = db.get(record_id)
return record

# Secure: verify authorization for the specific object
record = db.get(record_id)

if not user_can_access(current_user, record):
    raise AuthorizationError("Forbidden")

return record

### Step 3: Enforce authorization on every relevant request

Developers should enforce object-level authorization on the server side whenever an API accesses an object.

For example, before returning `/api/records/123`, the application should verify that the authenticated user has permission to access record `123`.

The authorization check should consider the authenticated user, the requested action, and the specific object. Object IDs should not be treated as proof that a user is authorized to access an object.

Authorization checks should not rely on the user interface hiding records or on object IDs being difficult to guess. The server must make the authorization decision.

## Summary

BOLA occurs when an API fails to enforce authorization for a specific object. Being authenticated does not automatically give a user permission to access every object in an application.

To prevent BOLA, APIs should perform server-side object-level authorization checks on requests involving protected objects. Developers should verify that the authenticated user is authorized to perform the requested action on the specific object rather than relying on client-side controls or unpredictable object IDs.

Authorization tests should also be used to verify that users cannot access objects belonging to other users.

## Further reading

* OWASP API Security Top 10 — API1:2023 Broken Object Level Authorization
* OWASP API Security Top 10 — API5:2023 Broken Function Level Authorization
* OWASP: Insecure Direct Object Reference (IDOR)
