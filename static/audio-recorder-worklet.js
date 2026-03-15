class PCMRecorderProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.targetSampleRate =
      options?.processorOptions?.targetSampleRate || 16000;
    this.pendingSamples = new Float32Array(0);
  }

  appendSamples(channelData) {
    if (!this.pendingSamples.length) {
      this.pendingSamples = new Float32Array(channelData);
      return;
    }

    const merged = new Float32Array(
      this.pendingSamples.length + channelData.length
    );
    merged.set(this.pendingSamples, 0);
    merged.set(channelData, this.pendingSamples.length);
    this.pendingSamples = merged;
  }

  flushPcmChunk() {
    if (!this.pendingSamples.length) {
      return null;
    }

    if (sampleRate === this.targetSampleRate) {
      const pcm16 = new Int16Array(this.pendingSamples.length);
      for (let i = 0; i < this.pendingSamples.length; i += 1) {
        const sample = Math.max(-1, Math.min(1, this.pendingSamples[i]));
        pcm16[i] = sample < 0 ? sample * 32768 : sample * 32767;
      }
      this.pendingSamples = new Float32Array(0);
      return pcm16;
    }

    const sampleRateRatio = sampleRate / this.targetSampleRate;
    const outputLength = Math.floor(this.pendingSamples.length / sampleRateRatio);
    if (outputLength <= 0) {
      return null;
    }

    const pcm16 = new Int16Array(outputLength);
    let inputOffset = 0;

    for (let outputIndex = 0; outputIndex < outputLength; outputIndex += 1) {
      const nextInputOffset = Math.min(
        this.pendingSamples.length,
        Math.round((outputIndex + 1) * sampleRateRatio)
      );
      let total = 0;
      let count = 0;

      for (let i = inputOffset; i < nextInputOffset; i += 1) {
        total += this.pendingSamples[i];
        count += 1;
      }

      const averagedSample = count ? total / count : 0;
      const clampedSample = Math.max(-1, Math.min(1, averagedSample));
      pcm16[outputIndex] =
        clampedSample < 0 ? clampedSample * 32768 : clampedSample * 32767;
      inputOffset = nextInputOffset;
    }

    this.pendingSamples = this.pendingSamples.slice(inputOffset);
    return pcm16;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0 || !input[0]) {
      return true;
    }

    this.appendSamples(input[0]);
    const pcm16 = this.flushPcmChunk();
    if (pcm16 && pcm16.length) {
      this.port.postMessage(pcm16.buffer, [pcm16.buffer]);
    }
    return true;
  }
}

registerProcessor("pcm-recorder", PCMRecorderProcessor);
