export class BodyTooLarge extends Error {}

export async function boundedBody(request: Request, limit: number): Promise<string> {
  const declared = Number(request.headers.get("content-length") ?? "0");
  if (declared > limit) throw new BodyTooLarge();
  if (!request.body) return "";
  const reader = request.body.getReader();
  const decoder = new TextDecoder();
  let result = "";
  let bytes = 0;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return result + decoder.decode();
    bytes += value.byteLength;
    if (bytes > limit) {
      await reader.cancel();
      throw new BodyTooLarge();
    }
    result += decoder.decode(value, { stream: true });
  }
}
