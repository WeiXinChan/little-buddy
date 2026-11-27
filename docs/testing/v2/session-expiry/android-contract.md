Android session expiry candidate

Backend PR148 fixed head 180ccbeb8ec08004e8aedb252048e6ce36150ec4 verified statically.
voice.py finish_session_expiry claims the expiring scope before await, revalidates
after bounded cleanup, sends explicit session/turn/revision/reason and standard
outer v/epoch. Client code29 is paired to that reviewed wire shape, not a deployment.

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
Code29 packaging follows this verified wire shape; backend approval/deployment and
real device expiry remain root-owned and unverified by the author.

Host TLS verification (not hardware or backend/provider proof): after normal matching
V2 Kotlin compilation, run under the shared build lock:

    scripts/with-build-lock env ANDROID_JAR=<approved SDK>/platforms/android-36/android.jar python3 scripts/test-session-expiry-client.py

It compiles the actual VoiceClient.kt (no receive injection) with cached Gson and
existing JVM Android ports; other current production dependencies use the matching
normal compile output (mtime checked). Temporary fixture certificate and synthetic
Bearer are test-only and deleted. Five independent sockets verify expired+duplicate,
conversation_ended, new scope replacing old session/turn/revision/epoch (wire barrier
before valid terminal), management-blocked terminal, and timeout with SERVER_TIMEOUT.
The peer closes after terminal frames; settled callbacks must not add failed().
A negative run with --negative-stale compiles a temporary gate mutant removing only
currentScope; unchanged stale/barrier assertion must fail. No mutation enters app.
The host runner explicitly exits after cleanup to avoid OkHttp idle dispatcher threads
extending fixture lifetime; subprocess timeout also kills/joins its exact test child.

Accepted terminal emits RuntimeStage.SESSION_END before close, scope=current diagnosticScope,
wire=SESSION_END, point=DISPATCH, source=EXPIRED for expiry and NONE for conversation end.
Rejected/stale/management events emit no normal-end stage; this is not CLIENT_FAIL.
Final static compatibility manifest is deployed backend0329097, not the older b568 reference.
