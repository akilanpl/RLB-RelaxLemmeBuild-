"""Bounded failover with one durable budget reservation per external call."""
from time import monotonic
from backend.app.ai.gateway import AIGateway, AIGatewayError


class TransientProviderError(AIGatewayError):
    pass


class FailoverGateway(AIGateway):
    def __init__(self, candidates, reserve=None, record=None):
        self.candidates = candidates
        self.reserve = reserve
        self.record = record

    def validate_configuration(self):
        self.candidates[0][1].validate_configuration()

    async def generate(self, request):
        attempts = []
        for index, (identity, gateway) in enumerate(self.candidates):
            if self.reserve:
                await self.reserve()
            started = monotonic()
            evidence = {**identity, 'attempt': index + 1, 'fallback_used': index > 0,
                        'fallback_reason': attempts[-1]['reason'] if attempts else None}
            try:
                # Every fallback must use its own model, with the same task context.
                response = await gateway.generate(request.model_copy(update={'model': None}))
            except AIGatewayError as exc:
                evidence.update(outcome='transient_failure' if isinstance(exc, TransientProviderError) else 'failed',
                                reason=str(exc), latency_ms=int((monotonic() - started) * 1000))
                attempts.append(evidence)
                if self.record:
                    await self.record(evidence)
                if not isinstance(exc, TransientProviderError) or index == len(self.candidates) - 1:
                    raise
            else:
                evidence.update(outcome='success', latency_ms=int((monotonic() - started) * 1000),
                                prompt_tokens=response.prompt_tokens, completion_tokens=response.completion_tokens)
                attempts.append(evidence)
                if self.record:
                    await self.record(evidence)
                return response.model_copy(update={'metadata': {**response.metadata, **evidence,
                                                               'provider_attempts': attempts}})
        raise AIGatewayError('No provider candidates configured.')
