/*
 * Repairs article headings such as “第十七条之一” that an earlier parser split
 * into heading “第十七条” and content prefix “之一”.  The body text is otherwise
 * unchanged.  The output remains a JavaScript LAW_DATABASE assignment.
 */
const fs = require('fs');
const vm = require('vm');

const databasePath = process.argv[2] || 'law_db.js';
const source = fs.readFileSync(databasePath, 'utf8');
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(source + ';this.database=LAW_DATABASE;', sandbox);
const database = sandbox.database;
let repaired = 0;

for (const document of database) {
  for (const article of document.articles || []) {
    if (article.structure_type !== 'article') continue;
    const match = String(article.content || '').match(/^(之[一二三四五六七八九十百千万零〇]+)[\s　]*/);
    if (!match || !/^第[一二三四五六七八九十百千万零〇]+条$/.test(article.article_title || '')) continue;
    article.number += match[1];
    article.article_title += match[1];
    article.content = article.content.slice(match[0].length);
    repaired += 1;
  }
}

if (!repaired) throw new Error('未找到需要修复的“条之…”标题；数据库未写入。');
fs.writeFileSync(databasePath, 'const LAW_DATABASE = ' + JSON.stringify(database, null, 2) + ';\n', 'utf8');
console.log(JSON.stringify({ repaired, documents: database.length }));
