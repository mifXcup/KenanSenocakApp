import { mkdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'

import pngToIco from 'png-to-ico'
import sharp from 'sharp'

const root = path.resolve(import.meta.dirname, '..')
const buildDir = path.join(root, 'build')
const svgPath = path.join(buildDir, 'icon.svg')
const sizes = [16, 24, 32, 48, 64, 128, 256]

await mkdir(buildDir, { recursive: true })
const svg = await readFile(svgPath)
const pngBuffers = await Promise.all(
  sizes.map((size) => sharp(svg).resize(size, size).png().toBuffer()),
)

await writeFile(path.join(buildDir, 'icon.png'), pngBuffers.at(-1))
await writeFile(path.join(buildDir, 'icon.ico'), await pngToIco(pngBuffers))

console.log('Windows uygulama ikonu hazır: build/icon.ico')
