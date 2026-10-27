# English Quest pixel characters

Production illustrations generated with the built-in image generation tool.
All four runtime PNGs have transparent backgrounds, are exactly 128 x 128 pixels,
and are displayed at 128 x 128 CSS pixels in both the practice panel and dashboard.
No responsive resizing, `object-fit` scaling, or percentage image dimensions are used.
They are bundled locally by Vite.
`battleCharacter[data-stage]` selects the illustration for the character's level.

| Stage | Level | File |
| --- | --- | --- |
| Apprentice | 1 | `apprentice-pixel-128.png` |
| Adventurer | 3 | `adventurer-pixel-128.png` |
| Quest knight | 5 | `knight-pixel-128.png` |
| Word hero | 10 | `hero-pixel-128.png` |

The original `*-pixel-v1.png` artwork is 1254 x 1254 pixels and is retained as
the editable source. Generate the runtime assets with
`node tools/prepare_character_sprites.cjs`. This applies high-quality Canvas
downsampling once, preserving alpha; it does not use an API or network.
The large originals are not imported into the runtime bundle.

Here 1:1 means one PNG pixel per CSS pixel. Physical monitor pixels also depend
on device pixel ratio and browser zoom; CSS cannot override those user settings.

## Final prompt set

### Apprentice

Reference: the initial original adventurer concept generated for this project.

Use case: style-transfer. Asset type: production PIXEL ART character sprite for English Quest RPG. Convert the provided adventurer reference to authentic low-resolution 16-bit JRPG pixel art. It MUST look like a sprite drawn on a 64x64 pixel grid and enlarged with nearest-neighbor scaling: large clearly visible square pixels, hard stair-step edges, dark 1-pixel outlines, limited 24-color palette, two or three flat shade values per material. No smooth illustration, no gradients, no anti-aliasing, no painterly texture, no 3D rendering. Same recognizable friendly young adventurer: tousled chestnut hair, brown eyes, soft sage-green cap, cream scarf, green tunic, brown boots, small silver sword, small blue book at belt. Stage 1 apprentice, no shield/cape/crown. Simplify to a charming 3-head-tall chibi game sprite, full body standing 3/4 view facing screen right, sword raised in the hand on screen right toward enemy. Whole body and sword inside the square canvas, consistent central sprite size with ~12% transparent empty space on every side. One character only. Genuinely transparent alpha background, no background color, no scene, no ground, no text, no frame, no watermark.

### Evolutions

Reference for every evolution: `apprentice-pixel-v1.png`.
Each was generated separately using this prompt with the indicated equipment text:

Use case: identity-preserve. Production transparent PIXEL ART character sprite for English Quest. Reference image 1 is the pixel art character whose identity, pose, silhouette scale, pixel size and exact 16-bit JRPG sprite style must be kept. Create this equipment evolution ONLY: **[equipment text]** Same warm brown eyes, chestnut tousled hair, cream scarf, blue book on belt, 3-head-tall proportions, friendly expression, stance and face direction as reference. Genuine blocky pixel art like a 64x64 sprite enlarged using nearest-neighbor: visible square pixels, hard stair-step contours, dark 1-pixel outline, restricted 24-color palette, two or three flat shades per material. NO smooth illustration, no gradients, no antialias, no painterly shading, no 3D. Full body and all equipment inside square canvas with 10% transparent padding on each side; boots aligned at same baseline as reference. Transparent alpha background, no scenery, no ground, no text, no UI, no watermark. Exactly one character.

- Adventurer: Level 3 ADVENTURER: azure-blue tunic and cap, small turquoise shield with gold rim held in the free left-side hand, same silver sword on screen right. No cape and no crown.
- Knight: Level 5 QUEST KNIGHT: indigo tunic and cap, small silver shoulder armor and bracers, short crimson cape behind the body blowing left, turquoise shield with silver rim in the left-side hand, same sword on screen right. No crown.
- Hero: Level 10 WORD HERO: ivory and royal-blue light armor with gold trim, small gold crown with turquoise gem instead of cap, blue cape blowing left behind body, turquoise shield with gold rim in left-side hand, upgraded silver sword with gold hilt on screen right.
