/**
 * 递增 patch 版本号，并同步 package-lock.json 里的两处 version 字段。
 *
 * 为什么需要同步 lock：electron-builder / npm 读取版本时可能取 package-lock，
 * 只改 package.json 会造成两处不一致（曾出现过同版本号打出不同内容的包）。
 *
 *   node scripts/bump-version.cjs           递增 patch（3.4.17 -> 3.4.18）
 *   node scripts/bump-version.cjs --dry-run 只打印，不写文件
 */
const fs = require('fs')
const path = require('path')

const CLIENT = path.join(__dirname, '..')
const pkgPath = path.join(CLIENT, 'package.json')
const lockPath = path.join(CLIENT, 'package-lock.json')
const dryRun = process.argv.includes('--dry-run')

const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'))
const parts = pkg.version.split('.').map(Number)
if (parts.length !== 3 || parts.some(isNaN)) {
  console.error(`Invalid version: ${pkg.version}`)
  process.exit(1)
}
parts[2] += 1
const next = parts.join('.')

if (dryRun) {
  console.log(`${pkg.version} -> ${next} (dry-run, not written)`)
  process.exit(0)
}

pkg.version = next
fs.writeFileSync(pkgPath, JSON.stringify(pkg, null, 2) + '\n', 'utf8')

// package-lock.json：顶层 version 与 packages[""].version 都要改
if (fs.existsSync(lockPath)) {
  try {
    const lock = JSON.parse(fs.readFileSync(lockPath, 'utf8'))
    lock.version = next
    if (lock.packages && lock.packages['']) lock.packages[''].version = next
    fs.writeFileSync(lockPath, JSON.stringify(lock, null, 2) + '\n', 'utf8')
  } catch (e) {
    console.warn('[bump] package-lock.json 同步失败（不阻塞）:', e.message)
  }
}

console.log(`Version bumped to ${next}`)
