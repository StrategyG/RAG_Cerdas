import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync("supabase/functions/institutional-rag-search/index.ts", "utf8");
const literalMatch = source.match(/const VIDEO_CITATION_RE = (\/(?:\\.|[^/])*\/[a-z]*);/);
assert.ok(literalMatch, "Edge Function must define the video citation regex as a regex literal");

assert.ok(source.includes("function timestampToSeconds(value: string): number"), "Edge Function must parse timestamps numerically");
assert.ok(
  source.includes("timestampToSeconds(videoMatch[2]) > timestampToSeconds(videoMatch[1])"),
  "Edge Function must reject video citations whose end timestamp is not after start"
);

const parserFunctionStart = source.indexOf("function timestampToSeconds(value: string): number");
assert.ok(parserFunctionStart >= 0, "Edge Function must define a timestamp parser");
const parserCallStart = source.indexOf("value.match(", parserFunctionStart);
const parserCallEnd = source.indexOf(");", parserCallStart);
assert.ok(parserCallStart >= 0 && parserCallEnd > parserCallStart, "timestamp parser must use a regex");
const parserLiteral = source.slice(parserCallStart + "value.match(".length, parserCallEnd).trim();
assert.ok(parserLiteral.startsWith("/") && parserLiteral.lastIndexOf("/") > 0, "timestamp parser must use a regex literal");
const parserSlash = parserLiteral.lastIndexOf("/");
const timestampParserRegex = new RegExp(parserLiteral.slice(1, parserSlash), parserLiteral.slice(parserSlash + 1));
function timestampToSeconds(value) {
  const match = value.match(timestampParserRegex);
  if (!match) return Number.NaN;
  return Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]);
}
assert.ok(timestampToSeconds("00:03:04") > timestampToSeconds("00:01:02"));
assert.ok(Number.isNaN(timestampToSeconds("bad timestamp")));
assert.ok(!(timestampToSeconds("00:01:02") > timestampToSeconds("00:01:02")));
assert.ok(!(timestampToSeconds("00:00:59") > timestampToSeconds("00:01:00")));

const literal = literalMatch[1];
const finalSlash = literal.lastIndexOf("/");
const regex = new RegExp(literal.slice(1, finalSlash), literal.slice(finalSlash + 1));

const valid = "[Video 00:01:02 - 00:03:04] Kutipan transkrip video.";
const match = valid.match(regex);
assert.ok(match, "must parse SQL-generated video markers");
assert.equal(match[1], "00:01:02");
assert.equal(match[2], "00:03:04");
assert.equal(valid.slice(match[0].length), "Kutipan transkrip video.");

assert.equal("[Video 10:20:30 - 10:21:00]".match(regex)?.[1], "10:20:30");
assert.equal("[Video 100:00:00 - 100:00:05] long video".match(regex)?.[2], "100:00:05");
assert.equal("[Video 00:61:02 - 00:03:04] invalid minute".match(regex), null);
assert.equal("[Video 00:01:62 - 00:03:04] invalid second".match(regex), null);
assert.equal("Video 00:01:02 - 00:03:04] missing opening bracket".match(regex), null);
assert.equal("[Video 00:01 - 00:03:04] malformed timestamp".match(regex), null);
assert.equal("prefix [Video 00:01:02 - 00:03:04] not at start".match(regex), null);

console.log("Video citation regex contract passed.");
