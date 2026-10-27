// Produce the exact-size PNGs shipped by the app. No API or network is used.
const {readFileSync, writeFileSync} = require('node:fs');
const {resolve} = require('node:path');
const {chromium} = require('playwright');

async function main() {
  const folder = resolve(__dirname, '../frontend/src/assets/characters');
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage();
    for (const name of ['apprentice', 'adventurer', 'knight', 'hero']) {
      const source = readFileSync(resolve(folder, `${name}-pixel-v1.png`));
      const result = await page.evaluate(async base64 => {
        const image = new Image();
        image.src = `data:image/png;base64,${base64}`;
        await image.decode();
        const canvas = document.createElement('canvas');
        canvas.width = canvas.height = 128;
        const context = canvas.getContext('2d');
        // Downsample only once when preparing assets. At runtime we draw 1:1.
        // High-quality filtering avoids skipping thin source lines, which was
        // happening when the browser shrank the large art with pixelated CSS.
        context.imageSmoothingEnabled = true;
        context.imageSmoothingQuality = 'high';
        context.drawImage(image, 0, 0, 128, 128);
        return {sourceSize: image.naturalWidth, png: canvas.toDataURL('image/png').split(',')[1]};
      }, source.toString('base64'));
      const output = Buffer.from(result.png, 'base64');
      writeFileSync(resolve(folder, `${name}-pixel-128.png`), output);
      console.log(`${name}: ${result.sourceSize}px -> 128px, ${output.length} bytes`);
    }
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
