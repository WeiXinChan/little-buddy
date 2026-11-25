R11 previously had a Session.retry primitive but no retry at the live provider
read call sites. Endpoint, plan and fact extraction now share one retry per input
revision in the original ResponseBudget. A turn/player rebuild does not replenish
it. A genuine new input revision may reserve its own retry, while stale operations
cannot consume or publish into that revision.

Only classified network/timeout faults at these three proposal-only ports are
eligible. Safety, synthesis, image generation, submission and arbitrary methods
cannot use this port. The second attempt is bounded by the existing remaining
response deadline and rechecks operation/revision/deadline on return. No idle TTL,
thinking interval or first-response boundary is reset. Planning/facts cannot retry
after confirmed or pending playback. There is no recursive retry, body logging,
cloud sample or device operation.

Targeted validation uses the actual VoicePeer response/bind/ACK pipeline and
synthetic providers: nine new methods cover recovery without duplicate speech,
endpoint-to-plan sharing across turn reconstruction, second failure, forbidden
stages, quota/safety/cancellation, deadline equality, revision changes before and
during retry, new genuine input, played-output rejection and management revoke.
The late-failure production response case also verifies no revoke/failure/audio
is sent into the new input.

Commands: `python3 -m unittest discover -s tests/v2 -p test_read_retry.py -v`,
plus affected `test_natural_management.py` and `test_safety_help.py` only. No old
full suite, Android build, CI retry, device, speech or paid provider call.
During test development the deadline fixture first hit its independent heartbeat
lease; that run was 7 pass/1 error. The fixture now keeps that lease live to test
the unchanged 15-second response deadline directly; no production lease was changed.
These software checks are not final network/device/long-session acceptance.
