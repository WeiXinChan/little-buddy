Android session expiry candidate (backend fixed head verification pending)

Wire: standard v=2 JSON text, type=session_end, reason=session_expired,
epoch/session/turn/revision copied from the expiring scope before cancellation.
conversation_ended remains supported. No failure frame grants scope or retry permission.

VoiceClient requires the current websocket/active generation and permitted foreground,
normal compatible scope, exact epoch/session/turn/revision, and no management pause.
An accepted terminal closes once before sessionEnded. Close revokes media/input/scope;
subsequent socket messages cannot consume or restart the old session.
Activity checks transport + page ticket before and after asynchronous release; only
confirmed release, focus, foreground, no management/help permit resumeConfigured.
The normal new connection is waiting-wake, never restores old context or playback.
Unknown reason and stale scope do not end a newer session. Generic failure timeout,
heartbeat/response errors, quota/voice/safety remain technical holds, not terminal retry.

No-local-help wire failures now pass fail() and record fixed source SERVER_TIMEOUT,
SERVER_QUOTA, SERVER_VOICE, SERVER_SAFETY, SERVER_AUTH, SERVER_UNAVAILABLE or
SERVER_UNKNOWN with existing activity/transport scope, wire=FAILURE, point=DISPATCH.
No arbitrary code/body/session ID or credentials are emitted. Accepted local safety
help keeps its existing route and now records SERVER_SAFETY as well.

code28 evidence shows real microphone operation about 10 minutes, then OTHER_ERROR;
no complete 420-second observation was obtained. Session TTL is a hypothesis until
backend differentiated wire evidence; no clock thresholds have been changed.
No code29 APK is frozen until backend actual fixed head/contract is verified.
