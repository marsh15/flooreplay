"""Role checks hold for direct HTTP callers in both environments."""
from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from flooreplay.api import create_app
from flooreplay.auth import Account, AuthSession, create_account
from flooreplay.db import session_scope


@pytest.mark.parametrize('mode', ['local', 'public'])
def test_roles_and_logout(mode, owner_headers, reviewer_headers):
    client = TestClient(create_app(mode))
    assert client.post('/api/v1/analyses/missing/ai-runs', json={'idempotency_key':'auth-proof-1'}).status_code == 401
    assert client.post('/api/v1/incidents/imports/preview', json={}, headers=reviewer_headers).status_code == 403
    assert client.post('/api/v1/incidents/imports/preview', json={}, headers=owner_headers).status_code == 422
    assert client.get('/api/v1/usage', headers=reviewer_headers).status_code == 403
    assert client.get('/api/v1/auth/me', headers=reviewer_headers).json()['role'] == 'reviewer'
    assert client.get('/api/v1/capabilities').json()['imports_enabled'] is False
    assert client.get('/api/v1/capabilities', headers=owner_headers).json()['imports_enabled'] is True


def test_session_hash_expiration_disabled_and_revocation():
    name = 'auth-' + uuid.uuid4().hex
    create_account(name, 'strong-enough-test-password', 'reviewer')
    client = TestClient(create_app(), client=(name, 50000))
    assert client.post('/api/v1/auth/login', json={'username':name,'password':'wrong'}).status_code == 401
    signed = client.post('/api/v1/auth/login', json={'username':name,'password':'strong-enough-test-password'}).json()
    token = signed['token']
    headers = {'Authorization':'Bearer '+token}
    with session_scope() as session:
        row = session.get(AuthSession, hashlib.sha256(token.encode()).hexdigest())
        assert row is not None and row.token_hash != token
        user = session.scalar(select(Account).where(Account.username == name))
        assert user.password_hash.startswith('$argon2id$')
    assert client.post('/api/v1/auth/logout', headers=headers).status_code == 200
    assert client.get('/api/v1/auth/me', headers=headers).status_code == 401
    signed = client.post('/api/v1/auth/login', json={'username':name,'password':'strong-enough-test-password'}).json()
    token = signed['token']
    headers = {'Authorization':'Bearer '+token}
    with session_scope() as session:
        session.get(AuthSession, hashlib.sha256(token.encode()).hexdigest()).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert client.get('/api/v1/auth/me', headers=headers).status_code == 401
    with session_scope() as session:
        user = session.scalar(select(Account).where(Account.username == name))
        user.disabled = True
    assert client.post('/api/v1/auth/login', json={'username':name,'password':'strong-enough-test-password'}).status_code == 401


def test_archived_owner_mutations_reject_anonymous():
    client = TestClient(create_app('local'))
    assert client.post('/api/v1/notes/parse', json={'text':'Recorded operator concern'}).status_code == 401
    assert client.post('/api/v1/comparisons', json={}).status_code == 401
