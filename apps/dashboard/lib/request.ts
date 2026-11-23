export class BodyTooLarge extends Error {}

export function boundedBody(request: Request | Response, limit: number): Promise<string>;
export function boundedBody(request: Request | Response, limit: number, binary: true): Promise<ArrayBuffer>;
export async function boundedBody(request: Request | Response, limit: number, binary = false) {
  const declared = Number(request.headers.get("content-length") ?? "0");
  if (declared > limit && request.body) {
    await request.body.cancel();
    throw new BodyTooLarge();
  }
  const reader = request.body?.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  if (reader) {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) {
        await reader.cancel();
        throw new BodyTooLarge();
      }
      chunks.push(value);
    }
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return binary ? bytes.buffer : new TextDecoder().decode(bytes);
}
