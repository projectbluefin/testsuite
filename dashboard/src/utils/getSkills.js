import fs from 'node:fs/promises';
import path from 'node:path';
import yaml from 'js-yaml';

// Split a markdown document into its leading `---` YAML front-matter block and
// the body. Skill docs are repository-controlled, so js-yaml's default (safe)
// schema is enough; a document without a front-matter block yields `{}`.
export function parseFrontMatter(raw) {
  const text = raw.replace(/^\uFEFF/, '');
  const lines = text.split(/\r?\n/);
  if (lines[0].trim() !== '---') return { data: {}, content: text };
  const end = lines.findIndex((line, i) => i > 0 && line.trim() === '---');
  if (end === -1) return { data: {}, content: text };
  const parsed = yaml.load(lines.slice(1, end).join('\n'));
  const data = parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  return { data, content: lines.slice(end + 1).join('\n') };
}

export async function loadSkills() {
  const TESTSUITE_SKILLS_PATH = path.resolve(process.cwd(), '../docs/skills');
  const COMMON_SKILLS_PATH = path.resolve(process.cwd(), '../../common/docs/skills');

  const sources = [
    { dir: TESTSUITE_SKILLS_PATH, repo: 'testsuite' },
    { dir: COMMON_SKILLS_PATH, repo: 'common' }
  ];
  let allSkills = [];

  for (const source of sources) {
    try {
      const files = await fs.readdir(source.dir);
      const mdFiles = files.filter(f => f.endsWith('.md') && f.toUpperCase() !== 'INDEX.MD');

      for (const file of mdFiles) {
        const fullPath = path.join(source.dir, file);
        const rawContent = await fs.readFile(fullPath, 'utf-8');
        const { data, content } = parseFrontMatter(rawContent);

        // Map tags and metadata
        const name = data.name || file.replace('.md', '').replace(/-/g, ' ').toUpperCase();
        const description = data.description || 'Operational skill specification.';
        const tags = data.tags || (data.metadata?.type ? [data.metadata.type] : []);
        const version = data.version || '1.0.0';

        allSkills.push({
          slug: `${source.repo}-${file.replace('.md', '')}`,
          repo: source.repo,
          filename: file,
          frontmatter: {
            name,
            description,
            tags,
            version,
          },
          content: content
        });
      }
    } catch (err) {
      console.warn(`Could not parse skills under ${source.dir}:`, err.message);
    }
  }
  return allSkills;
}
