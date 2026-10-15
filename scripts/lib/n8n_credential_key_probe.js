// n8n_credential_key_probe.js — does the n8n encryption key decrypt a restored credential? (DR audit DD10, 2026-10-15)
//
// Run INSIDE the n8n app container by scripts/n8n_lab_restore_drill.sh:
//   printf '%s' "<credentials_entity.data of one restored row>" | docker exec -i m8m-n8n node -e "$(cat this file)"
// The key is read where n8n itself reads it (N8N_ENCRYPTION_KEY, else <N8N_USER_FOLDER or ~>/.n8n/config
// "encryptionKey"); it never leaves the container. Prints exactly ONE word and nothing else — never the key, never
// plaintext, never the ciphertext:
//   KEY_OK           decrypted and the plaintext parses as a JSON object (a credential's data shape)
//   KEY_BAD          a key is present but the ciphertext does not decrypt to a JSON object (wrong key / corrupt row)
//   KEY_UNAVAILABLE  no key found in the container
//   NO_CIPHERTEXT    nothing on stdin (no credential row to test)
// Format: n8n Cipher = CryptoJS AES-256-CBC, base64 "Salted__" + 8-byte salt, key/iv from EVP_BytesToKey(MD5).
// Exit 0 for KEY_OK, 1 otherwise. Tests: tests/test_n8n_lab_restore_drill_verdict_20261015.py (node, synthetic key).
'use strict';
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const os = require('os');

function out(word) {
  process.stdout.write(word + '\n');
  process.exit(word === 'KEY_OK' ? 0 : 1);
}

function readKey() {
  if (process.env.N8N_ENCRYPTION_KEY) return process.env.N8N_ENCRYPTION_KEY;
  const base = process.env.N8N_USER_FOLDER || os.homedir();
  try {
    const cfg = JSON.parse(fs.readFileSync(path.join(base, '.n8n', 'config'), 'utf8'));
    return cfg && typeof cfg.encryptionKey === 'string' ? cfg.encryptionKey : '';
  } catch (e) {
    return '';
  }
}

function evpKeyIv(password, salt) {
  let prev = Buffer.alloc(0);
  let acc = Buffer.alloc(0);
  while (acc.length < 48) {
    prev = crypto.createHash('md5').update(Buffer.concat([prev, password, salt])).digest();
    acc = Buffer.concat([acc, prev]);
  }
  return { key: acc.subarray(0, 32), iv: acc.subarray(32, 48) };
}

let input = '';
try {
  input = fs.readFileSync(0, 'utf8').trim();
} catch (e) {
  input = '';
}
if (!input) out('NO_CIPHERTEXT');
const keyText = readKey();
if (!keyText) out('KEY_UNAVAILABLE');
try {
  const raw = Buffer.from(input, 'base64');
  if (raw.length < 32 || raw.subarray(0, 8).toString('latin1') !== 'Salted__') out('KEY_BAD');
  const { key, iv } = evpKeyIv(Buffer.from(keyText, 'utf8'), raw.subarray(8, 16));
  const d = crypto.createDecipheriv('aes-256-cbc', key, iv);
  const plain = Buffer.concat([d.update(raw.subarray(16)), d.final()]).toString('utf8');
  const obj = JSON.parse(plain);
  out(obj && typeof obj === 'object' && !Array.isArray(obj) ? 'KEY_OK' : 'KEY_BAD');
} catch (e) {
  out('KEY_BAD');
}
