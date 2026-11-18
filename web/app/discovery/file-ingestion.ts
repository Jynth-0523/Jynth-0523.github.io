import { AsyncUnzipInflate, Unzip } from "fflate";

export const MAX_UNCOMPRESSED_CSV_BYTES = 200 * 1024 * 1024;

export async function extractCsv(file: File): Promise<File> {
  if (!file.name.toLowerCase().endsWith(".zip")) return file;
  return new Promise<File>(async (resolve, reject) => {
    const csvEntries: Array<{ name: string; chunks: Uint8Array[]; size: number; complete: boolean }> = [];
    let archiveFinished = false;
    const unzipper = new Unzip((entry) => {
      if (!entry.name.toLowerCase().endsWith(".csv") || entry.name.startsWith("__MACOSX/")) return;
      const record = { name: entry.name, chunks: [] as Uint8Array[], size: 0, complete: false };
      csvEntries.push(record);
      entry.ondata = (error, chunk, final) => {
        if (error) return reject(error);
        record.size += chunk.byteLength;
        if (record.size > MAX_UNCOMPRESSED_CSV_BYTES) return reject(new Error("The CSV inside the ZIP exceeds the 200 MB browser limit."));
        record.chunks.push(chunk);
        if (final) {
          record.complete = true;
          finish();
        }
      };
      entry.start();
    });
    unzipper.register(AsyncUnzipInflate);
    function finish() {
      if (!archiveFinished || csvEntries.some((entry) => !entry.complete)) return;
      if (csvEntries.length !== 1) {
        reject(new Error(csvEntries.length === 0 ? "The ZIP does not contain a CSV file." : "The ZIP must contain exactly one CSV file."));
        return;
      }
      const selected = csvEntries[0];
      const parts = selected.chunks.map((chunk) => chunk.buffer.slice(chunk.byteOffset, chunk.byteOffset + chunk.byteLength) as ArrayBuffer);
      resolve(new File(parts, selected.name.split("/").pop() ?? "panel.csv", { type: "text/csv" }));
    }
    try {
      const reader = file.stream().getReader();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        unzipper.push(value, false);
      }
      archiveFinished = true;
      unzipper.push(new Uint8Array(), true);
      window.setTimeout(finish, 0);
    } catch (error) {
      reject(error);
    }
  });
}

