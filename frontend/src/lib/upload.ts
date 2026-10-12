/** Where one file is in a multi-file upload. */
export type FileUploadState =
  | { state: "waiting" }
  | { state: "uploading" }
  | { state: "queued" }
  | { state: "failed"; message: string };

export interface UploadResult<F, J> {
  queued: { file: F; job: J }[];
  failed: { file: F; message: string }[];
}

/**
 * Upload files one after another. A file that fails does not stop the others: each
 * outcome is reported through `onState` as it happens, so a queued file can be taken
 * off the list at once and is never uploaded twice.
 */
export async function uploadAll<F, J>(
  files: readonly F[],
  upload: (file: F) => Promise<J>,
  onState: (file: F, state: FileUploadState) => void = () => {},
): Promise<UploadResult<F, J>> {
  const result: UploadResult<F, J> = { queued: [], failed: [] };
  files.forEach((f) => onState(f, { state: "waiting" }));
  for (const file of files) {
    onState(file, { state: "uploading" });
    try {
      const job = await upload(file);
      result.queued.push({ file, job });
      onState(file, { state: "queued" });
    } catch (e) {
      const message = e instanceof Error && e.message ? e.message : "The upload failed";
      result.failed.push({ file, message });
      onState(file, { state: "failed", message });
    }
  }
  return result;
}
