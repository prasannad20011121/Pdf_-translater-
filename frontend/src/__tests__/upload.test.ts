// Finding 36 (h): one failing file does not stop the batch, and queued files are reported at once.
import assert from "node:assert/strict";
import { test } from "node:test";
import { uploadAll, type FileUploadState } from "../lib/upload.ts";

test("a failing file is reported and the rest are still uploaded", async () => {
  const sent: string[] = [];
  const upload = async (name: string) => {
    sent.push(name);
    if (name === "B.pdf") throw new Error("Password-protected PDFs are not supported yet.");
    return { id: `job-${name}` };
  };
  const log: [string, FileUploadState["state"]][] = [];
  const r = await uploadAll(["A.pdf", "B.pdf", "C.pdf"], upload, (f, st) => log.push([f, st.state]));

  assert.deepEqual(sent, ["A.pdf", "B.pdf", "C.pdf"]);
  assert.deepEqual(r.queued.map((q) => q.file), ["A.pdf", "C.pdf"]);
  assert.deepEqual(r.failed, [{ file: "B.pdf", message: "Password-protected PDFs are not supported yet." }]);
  // A is reported as queued before B is even tried, so the page can take it off the list.
  assert.ok(log.findIndex((e) => e[0] === "A.pdf" && e[1] === "queued") < log.findIndex((e) => e[0] === "B.pdf" && e[1] === "uploading"));
  assert.deepEqual(log.filter((e) => e[0] === "B.pdf").map((e) => e[1]), ["waiting", "uploading", "failed"]);
});

test("retrying only the failed file never re-uploads one that was queued", async () => {
  let list = ["A.pdf", "B.pdf"];
  let failB = true;
  const sent: string[] = [];
  const upload = async (name: string) => {
    sent.push(name);
    if (name === "B.pdf" && failB) throw new Error("not readable");
    return name;
  };
  const onState = (f: string, st: FileUploadState) => {
    if (st.state === "queued") list = list.filter((x) => x !== f);
  };
  await uploadAll(list, upload, onState);
  assert.deepEqual(list, ["B.pdf"]);
  failB = false;
  await uploadAll(list, upload, onState);
  assert.deepEqual(sent, ["A.pdf", "B.pdf", "B.pdf"]);
  assert.deepEqual(list, []);
});

test("an error without a message still gets one", async () => {
  const r = await uploadAll(["A.pdf"], async () => {
    throw new Error("");
  });
  assert.equal(r.failed[0].message, "The upload failed");
});
