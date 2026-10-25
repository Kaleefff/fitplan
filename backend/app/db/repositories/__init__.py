"""Repositories over the DB-01 models.

Each method runs in its own transaction: the token rules of B-02 must keep a family
revocation even when the request then answers 401.
"""
