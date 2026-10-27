export function sentenceClip(buffer: AudioBuffer, startSeconds: number, endSeconds: number): Blob {
  const rate = buffer.sampleRate;
  const first = Math.max(0, Math.min(buffer.length, Math.floor(startSeconds * rate)));
  const last = Math.max(first, Math.min(buffer.length, Math.floor(endSeconds * rate)));
  if (last <= first) throw new Error('The selected sentence has no audio samples.');
  const channels = Math.min(buffer.numberOfChannels, 2);
  const frames = last - first;
  const bytes = new ArrayBuffer(44 + frames * channels * 2);
  const view = new DataView(bytes);
  const write = (offset: number, value: string) => { for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i)); };
  write(0, 'RIFF'); view.setUint32(4, bytes.byteLength - 8, true); write(8, 'WAVE');
  write(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, channels, true); view.setUint32(24, rate, true);
  view.setUint32(28, rate * channels * 2, true); view.setUint16(32, channels * 2, true);
  view.setUint16(34, 16, true); write(36, 'data'); view.setUint32(40, frames * channels * 2, true);
  const samples = Array.from({length: channels}, (_, channel) => buffer.getChannelData(channel));
  for (let frame = 0; frame < frames; frame++) {
    for (let channel = 0; channel < channels; channel++) {
      const value = Math.max(-1, Math.min(1, samples[channel][first + frame]));
      view.setInt16(44 + (frame * channels + channel) * 2, value < 0 ? value * 32768 : value * 32767, true);
    }
  }
  return new Blob([bytes], {type: 'audio/wav'});
}
