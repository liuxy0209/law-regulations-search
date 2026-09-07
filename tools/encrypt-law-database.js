/*
 * Encrypts the browser law database with AES-256-GCM. The password is supplied
 * only through LAW_DATABASE_PASSWORD and is never written to the repository.
 * The output remains a JavaScript asset so the protected site also works from
 * file:// when opened locally.
 */
const crypto = require('crypto');
const fs = require('fs');
const vm = require('vm');

const databasePath = process.argv[2] || 'law_db.js';
const outputPaths = process.argv.slice(3);
const password = process.env.LAW_DATABASE_PASSWORD;
const nextPassword = process.env.NEW_LAW_DATABASE_PASSWORD || password;
if (!password || !nextPassword) throw new Error('请通过环境变量 LAW_DATABASE_PASSWORD 提供口令。');

function loadDatabase(source) {
  const sandbox = {};
  vm.createContext(sandbox);
  vm.runInContext(source + ';this.__lawDatabase=typeof LAW_DATABASE === "undefined" ? null : LAW_DATABASE;', sandbox);
  if (Array.isArray(sandbox.__lawDatabase)) return sandbox.__lawDatabase;
  if (!sandbox.LAW_DATABASE_ENCRYPTED) throw new Error('未识别的法律库文件格式。');
  const encrypted = sandbox.LAW_DATABASE_ENCRYPTED;
  const key = crypto.pbkdf2Sync(password, Buffer.from(encrypted.salt, 'base64'), encrypted.kdf.iterations, 32, encrypted.kdf.hash.replace('-', '').toLowerCase());
  const decipher = crypto.createDecipheriv('aes-256-gcm', key, Buffer.from(encrypted.iv, 'base64'));
  decipher.setAuthTag(Buffer.from(encrypted.tag, 'base64'));
  return JSON.parse(Buffer.concat([decipher.update(Buffer.from(encrypted.ciphertext, 'base64')), decipher.final()]).toString('utf8'));
}

const database = loadDatabase(fs.readFileSync(databasePath, 'utf8'));
const salt = crypto.randomBytes(16);
const iv = crypto.randomBytes(12);
const iterations = 600000;
const hash = 'SHA-256';
const key = crypto.pbkdf2Sync(nextPassword, salt, iterations, 32, 'sha256');
const cipher = crypto.createCipheriv('aes-256-gcm', key, iv);
const ciphertext = Buffer.concat([cipher.update(JSON.stringify(database), 'utf8'), cipher.final()]);
const payload = {
  version: 1,
  kdf: { name: 'PBKDF2', hash, iterations },
  salt: salt.toString('base64'),
  iv: iv.toString('base64'),
  ciphertext: ciphertext.toString('base64'),
  tag: cipher.getAuthTag().toString('base64')
};
const output = 'globalThis.LAW_DATABASE_ENCRYPTED = ' + JSON.stringify(payload) + ';\n';
(outputPaths.length ? outputPaths : [databasePath]).forEach((outputPath) => fs.writeFileSync(outputPath, output, 'utf8'));
console.log(JSON.stringify({ encrypted: true, documents: database.length, iterations, outputs: outputPaths.length || 1 }));
