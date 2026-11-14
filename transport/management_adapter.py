"""Approval-consistency-checked HTTP adapter for sandbox predefined actions."""

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import UUID, uuid4, uuid5

import httpx

from shared.v1 import ActionKey, Approval, ExecutionResult, RemediationProposal, map_sandbox_execution


@dataclass(frozen=True, repr=False)
class ManagementConfig:
    origin: str
    token: str = field(repr=False)
    timeout_seconds: float = 3.0

    def __post_init__(self):
        parsed = urlsplit(self.origin)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or
                parsed.username is not None or parsed.password is not None or
                parsed.path not in ('', '/') or parsed.query or parsed.fragment or
                (parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1', 'management'))):
            raise ValueError('Invalid sandbox management origin')
        try:
            parsed.port
        except ValueError:
            raise ValueError('Invalid sandbox management origin') from None
        if not isinstance(self.token, str) or not self.token.strip():
            raise ValueError('Sandbox management token is required')
        if not 0 < self.timeout_seconds <= 15:
            raise ValueError('Sandbox management timeout must be between 0 and 15 seconds')
        object.__setattr__(self, 'origin', self.origin.rstrip('/'))

    @classmethod
    def from_env(cls):
        return cls(origin=os.getenv('SANDBOX_MANAGEMENT_URL', ''),
                   token=os.getenv('SANDBOX_MANAGEMENT_TOKEN', ''))


def _outcome(proposal: RemediationProposal, state: str, detail: str) -> ExecutionResult:
    return ExecutionResult(id=uuid4(), proposal_id=proposal.id, action_key=proposal.action_key,
                           state=state, requested_at=datetime.now(timezone.utc), detail=detail)


class SandboxManagementAdapter:
    def __init__(self, config: ManagementConfig, client: httpx.Client | None = None):
        if not isinstance(config, ManagementConfig):
            raise TypeError('ManagementConfig is required')
        self._config = config
        self._client = client

    def execute(self, proposal: RemediationProposal, approval: Approval, attempt_id: UUID) -> ExecutionResult:
        """One bounded HTTP attempt; caller must persist and reuse attempt_id on retry."""
        if not isinstance(proposal, RemediationProposal) or not isinstance(approval, Approval):
            raise TypeError('Validated proposal and approval are required')
        if not isinstance(proposal.action_key, ActionKey):
            raise ValueError('Unsupported predefined action')
        proposal = RemediationProposal.model_validate_json(proposal.model_dump_json())
        approval = Approval.model_validate_json(approval.model_dump_json())
        if approval.proposal_id != proposal.id or approval.decision != 'approved':
            raise ValueError('Matching approved record is required')
        if not isinstance(attempt_id, UUID):
            raise TypeError('Stable UUID attempt_id is required')
        key = str(uuid5(proposal.id, str(attempt_id)))
        payload = {'action_key': proposal.action_key.value, 'idempotency_key': key}
        headers = {'Authorization': f'Bearer {self._config.token}'}
        owned_client = self._client is None
        client = self._client or httpx.Client(timeout=self._config.timeout_seconds, follow_redirects=False)
        try:
            response = client.post(self._config.origin + '/management/actions',
                                   json=payload, headers=headers,
                                   timeout=self._config.timeout_seconds, follow_redirects=False)
        except httpx.RequestError:
            return _outcome(proposal, 'indeterminate', 'transport_uncertain_reconcile')
        finally:
            if owned_client:
                client.close()

        if response.status_code in (401, 403):
            return _outcome(proposal, 'failed', 'authentication_rejected')
        if response.status_code == 409:
            return _outcome(proposal, 'failed', 'idempotency_conflict')
        if 300 <= response.status_code < 400:
            return _outcome(proposal, 'indeterminate', 'redirect_rejected_reconcile')
        if response.status_code >= 500:
            try:
                failure = response.json()
            except ValueError:
                failure = None
            if isinstance(failure, dict) and failure.get('state') == 'failed' and failure.get('action_key', proposal.action_key.value) == proposal.action_key.value:
                return map_sandbox_execution(proposal, {'state': 'failed', 'detail': 'management_reported_failure'})
            return _outcome(proposal, 'indeterminate', 'upstream_error_reconcile')
        try:
            body = response.json()
        except ValueError:
            return _outcome(proposal, 'indeterminate', 'invalid_response_reconcile')
        if not isinstance(body, dict):
            return _outcome(proposal, 'indeterminate', 'invalid_response_reconcile')
        if response.status_code != 200:
            return _outcome(proposal, 'failed', 'management_rejected_request')
        if set(body) != {'execution_id', 'action_key', 'state', 'requested_at'} or body.get('state') not in ('applied', 'unsupported'):
            return _outcome(proposal, 'indeterminate', 'invalid_response_reconcile')
        try:
            return map_sandbox_execution(proposal, body)
        except (ValueError, TypeError):
            return _outcome(proposal, 'indeterminate', 'invalid_response_reconcile')
