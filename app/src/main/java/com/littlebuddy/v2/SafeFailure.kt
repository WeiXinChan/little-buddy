package com.littlebuddy.v2
/** Class and project source positions only. Never read Throwable.message/cause text. */
internal object SafeFailure {
 private fun name(s:String)=s.replace(Regex("[^A-Za-z0-9_.$]"),"_").take(160)
 fun describe(error:Throwable):String {
  val frames=error.stackTrace.filter{it.className.startsWith("com.littlebuddy.")}.take(6)
  return "class=${name(error.javaClass.name)} source="+frames.joinToString("|"){"${name(it.className)}.${name(it.methodName)}(${name(it.fileName?:"Unknown")}:${it.lineNumber})"}
 }
}
