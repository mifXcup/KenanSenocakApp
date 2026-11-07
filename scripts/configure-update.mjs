import { readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'

const source = process.argv[2]?.trim() || process.env.GITHUB_REPOSITORY || ''
const match = source.match(/(?:github\.com[/:])?([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+?)(?:\.git)?\/?$/)

if (!match) {
  throw new Error('GitHub deposunu "sahip/depo" veya "https://github.com/sahip/depo" olarak verin.')
}

const [, owner, repo] = match
const target = path.resolve(import.meta.dirname, '..', 'desktop', 'update-config.cjs')
const content = `// Bu dosya npm run configure:update tarafından oluşturulur.\nmodule.exports = Object.freeze({\n  provider: 'github',\n  owner: '${owner}',\n  repo: '${repo}',\n})\n`
await readFile(target, 'utf8') // Yanlış dizinde çalışmayı erken fark et.
await writeFile(target, content, 'utf8')
console.log(`Uygulama güncelleme kaynağı ayarlandı: ${owner}/${repo}`)
