import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync("supabase/functions/institutional-rag-search/index.ts", "utf8");
const literalMatch = source.match(/const VIDEO_CITATION_RE = (\/(?:\\.|[^/])*\/[a-z]*);/);
assert.ok(literalMatch, "Edge Function must define the video citation regex as a regex literal");

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
assert.equal("Video 00:01:02 - 00:03:04] missing opening bracket".match(regex), null);
assert.equal("[Video 00:01 - 00:03:04] malformed timestamp".match(regex), null);
assert.equal("prefix [Video 00:01:02 - 00:03:04] not at start".match(regex), null);

console.log("Video citation regex contract passed.");
