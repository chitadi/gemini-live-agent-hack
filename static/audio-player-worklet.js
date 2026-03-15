class PCMPlayerProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.chunks = [];
    this.chunkIndex = 0;
    this.sampleIndex = 0;

    this.port.onmessage = (event) => {
      if (event.data && event.data.type === "clear") {
        this.chunks = [];
        this.chunkIndex = 0;
        this.sampleIndex = 0;
        return;
      }

      if (event.data instanceof ArrayBuffer) {
        this.chunks.push(new Int16Array(event.data));
      }
    };
  }

  process(_inputs, outputs) {
    const outputChannels = outputs[0];
    if (!outputChannels || outputChannels.length === 0) {
      return true;
    }

    const frameLength = outputChannels[0].length;
    for (let i = 0; i < frameLength; i += 1) {
      let sample = 0;

      if (this.chunkIndex < this.chunks.length) {
        const currentChunk = this.chunks[this.chunkIndex];
        sample = currentChunk[this.sampleIndex] / 32768;
        this.sampleIndex += 1;

        if (this.sampleIndex >= currentChunk.length) {
          this.sampleIndex = 0;
          this.chunkIndex += 1;

          if (this.chunkIndex > 6) {
            this.chunks = this.chunks.slice(this.chunkIndex);
            this.chunkIndex = 0;
          }
        }
      }

      for (let channel = 0; channel < outputChannels.length; channel += 1) {
        outputChannels[channel][i] = sample;
      }
    }

    return true;
  }
}

registerProcessor("pcm-player", PCMPlayerProcessor);
