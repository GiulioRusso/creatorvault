/*
 * creatorvault: export Meta Business Suite drafts.
 *
 * Business Suite has no export for drafts. Paste this script in the Chrome
 * DevTools console (Cmd+Option+J / Ctrl+Shift+J) on
 *   Business Suite > Content > Posts & reels > Drafts
 * after setting the date filter and scrolling the list to the bottom (rows
 * only load while you scroll).
 *
 * For every loaded draft it opens the draft editor in a hidden frame (nothing
 * is saved), reads the full caption and the full-size media, and downloads one
 * meta-drafts-YYYYMMDD-HHMM.zip with drafts.json + the media, in the format of
 * paths.meta_drafts. Put the zip in that folder and run `creatorvault build`.
 */
(async () => {
  const CONFIG = {
    // Keep only drafts created in these ranges, e.g. [["2024-12-01", "2024-12-31"]].
    // Empty = every loaded draft (the Business Suite date filter usually suffices).
    periods: [],
    limit: 0, // stop after N drafts; 3 is a good first test
    dryRun: false, // true = list the drafts in the console, no download
    minImageSide: 600, // smaller images are thumbnails, not media
    editorTimeoutS: 30,
  };

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const log = (...a) => console.log("%c[creatorvault]", "color:#1877f2;font-weight:bold", ...a);

  if (!/\/latest\/posts\/draft_posts/.test(location.pathname)) {
    alert("Open Business Suite > Content > Posts & reels > Drafts, then run the script again.");
    return;
  }

  // 1. Drafts loaded in the list (React props hold the id, date and type).
  const itemOf = (row) => {
    const key = Object.keys(row).find((k) => k.startsWith("__reactFiber"));
    let fiber = key && row[key];
    for (let i = 0; i < 10 && fiber; i++, fiber = fiber.return) {
      const it = fiber.memoizedProps && fiber.memoizedProps.item;
      if (it && it.id && it.title !== undefined) return it;
    }
    return null;
  };
  const stamp = (t) => String((t && (t.$1 || t)) || "");
  const inPeriods = (day) =>
    !CONFIG.periods.length || CONFIG.periods.some(([a, b]) => day >= a && day <= b);

  const seen = new Set();
  let items = [...document.querySelectorAll("[role=row]")]
    .filter((r) => r.querySelectorAll("[role=gridcell]").length >= 3)
    .map(itemOf)
    .filter((it) => it && !seen.has(it.id) && seen.add(it.id))
    .map((it) => ({
      id: String(it.id),
      created: stamp(it.creationTime),
      caption: it.title || "",
      video: /VIDEO|REEL/i.test(`${it.mediaType} ${it.postType}`),
    }));
  log(`${items.length} drafts loaded (scroll further to load more).`);
  items = items.filter((it) => inPeriods(it.created.slice(0, 10)));
  if (CONFIG.limit) items = items.slice(0, CONFIG.limit);
  log(`${items.length} drafts selected.`);
  if (!items.length) return;

  // 2. Full caption and media from each draft's editor, in a hidden frame.
  const qs = new URLSearchParams(location.search);
  const editorUrl = (id) =>
    `/latest/composer/?asset_id=${qs.get("asset_id")}&business_id=${qs.get("business_id")}` +
    `&business_content_id=${id}&ref=biz_web_content_manager_draft_edit&context_ref=POSTS`;
  const frame = document.createElement("iframe");
  frame.style.cssText =
    "position:fixed;right:0;bottom:0;width:1280px;height:1000px;opacity:0.01;pointer-events:none;z-index:-1";
  document.body.appendChild(frame);

  const isMedia = (im) =>
    /fbcdn\.net/.test(im.src) && !/rsrc\.php/.test(im.src) &&
    im.naturalWidth >= CONFIG.minImageSide && im.naturalHeight >= CONFIG.minImageSide;

  const readEditor = async (id) => {
    frame.src = editorUrl(id);
    const t0 = Date.now();
    let state = "editor not ready";
    while (Date.now() - t0 < CONFIG.editorTimeoutS * 1000) {
      await sleep(1000);
      let doc;
      try { doc = frame.contentDocument; } catch { continue; }
      if (!doc || !/composer/.test(doc.location.pathname)) continue;
      const editor = doc.querySelector("[contenteditable=true]");
      const videos = [...doc.querySelectorAll("video")].map((v) => v.currentSrc || v.src)
        .filter((u) => /^https:/.test(u));
      if (editor && ([...doc.querySelectorAll("img")].some(isMedia) || videos.length)) {
        await sleep(1500); // let every carousel image load
        const byFile = new Map(); // preview and editor show the same photo twice
        for (const im of [...doc.querySelectorAll("img")].filter(isMedia)) {
          const file = new URL(im.src).pathname.split("/").pop();
          const prev = byFile.get(file);
          if (!prev || im.naturalWidth > prev.naturalWidth) byFile.set(file, im);
        }
        return {
          caption: editor.innerText.replace(/​/g, "").trim(),
          media: [...[...byFile.values()].map((im) => ["jpg", im.src]),
                  ...[...new Set(videos)].map((u) => ["mp4", u])],
        };
      }
      state = editor ? "no media found" : "editor not ready";
    }
    throw new Error(`timeout: ${state}`);
  };

  // 3. A stored (uncompressed) zip: enough for jpg/mp4/json, no library needed.
  const CRC = new Uint32Array(256).map((_, n) => {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });
  const crc32 = (buf) => {
    let c = 0xffffffff;
    for (let i = 0; i < buf.length; i++) c = CRC[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  };
  const zip = (files) => {
    const enc = new TextEncoder(), parts = [], central = [];
    let offset = 0;
    for (const f of files) {
      const name = enc.encode(f.name), crc = crc32(f.data), size = f.data.length;
      const h = new DataView(new ArrayBuffer(30));
      h.setUint32(0, 0x04034b50, true); h.setUint16(4, 20, true); h.setUint16(6, 0x0800, true);
      h.setUint32(14, crc, true); h.setUint32(18, size, true); h.setUint32(22, size, true);
      h.setUint16(26, name.length, true);
      parts.push(new Uint8Array(h.buffer), name, f.data);
      const c = new DataView(new ArrayBuffer(46));
      c.setUint32(0, 0x02014b50, true); c.setUint16(4, 20, true); c.setUint16(6, 20, true);
      c.setUint16(8, 0x0800, true); c.setUint32(16, crc, true); c.setUint32(20, size, true);
      c.setUint32(24, size, true); c.setUint16(28, name.length, true); c.setUint32(42, offset, true);
      central.push(new Uint8Array(c.buffer), name);
      offset += 30 + name.length + size;
    }
    const size = central.reduce((s, p) => s + p.length, 0);
    const e = new DataView(new ArrayBuffer(22));
    e.setUint32(0, 0x06054b50, true); e.setUint16(8, files.length, true);
    e.setUint16(10, files.length, true); e.setUint32(12, size, true); e.setUint32(16, offset, true);
    return new Blob([...parts, ...central, new Uint8Array(e.buffer)], { type: "application/zip" });
  };

  // 4. Run.
  const files = [], drafts = [], failed = [];
  for (const [i, it] of items.entries()) {
    try {
      const ed = await readEditor(it.id);
      const media = [];
      for (const [j, [ext, url]] of ed.media.entries()) {
        const name = `${it.id}-${String(j + 1).padStart(2, "0")}.${ext}`;
        if (!CONFIG.dryRun) {
          files.push({ name, data: new Uint8Array(await (await fetch(url)).arrayBuffer()) });
        }
        media.push(name);
      }
      const reel = it.video || (media.length === 1 && media[0].endsWith(".mp4"));
      drafts.push({
        id: it.id,
        caption: ed.caption || it.caption,
        media,
        updated: it.created,
        content_type: reel ? "reels" : "posts",
      });
      log(`${i + 1}/${items.length} ok   ${it.created.slice(0, 10)}  ${media.length} media  ${drafts.at(-1).caption.slice(0, 60)}`);
    } catch (err) {
      failed.push({ id: it.id, created: it.created, error: String(err.message || err) });
      log(`${i + 1}/${items.length} FAILED ${it.id}: ${err.message || err}`);
    }
  }
  frame.remove();
  log(`Done: ${drafts.length} exported, ${failed.length} failed.`);
  if (failed.length) console.table(failed);
  if (CONFIG.dryRun) {
    console.table(drafts.map((d) => ({ id: d.id, updated: d.updated, media: d.media.length, caption: d.caption.slice(0, 70) })));
    return;
  }

  files.unshift({ name: "drafts.json", data: new TextEncoder().encode(JSON.stringify(drafts, null, 2)) });
  const now = new Date(), pad = (n) => String(n).padStart(2, "0");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(zip(files));
  a.download = `meta-drafts-${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}.zip`;
  document.body.appendChild(a); a.click(); a.remove();
  log(`Downloaded ${a.download}: put it in paths.meta_drafts and run \`creatorvault build\`.`);
})();
