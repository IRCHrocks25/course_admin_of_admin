(function (global) {
    'use strict';

    function escapeHtml(value) {
        return (value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function getCsrfToken() {
        const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : '';
    }

    function parseContentBlocks(rawValue) {
        try {
            const parsed = JSON.parse(rawValue || '{"blocks": []}');
            if (parsed && Array.isArray(parsed.blocks)) return parsed.blocks;
            if (Array.isArray(parsed)) return parsed;
        } catch (error) {}
        return [];
    }

    function isDirectNoteVideo(rawUrl, source) {
        const url = (rawUrl || '').trim();
        if (!url || /^(javascript|data|vbscript):/i.test(url)) return false;
        if ((source || '').toLowerCase() === 'upload') return true;
        if (/\.(webm|mp4|ogg|ogv|mov|m4v)(\?|#|$)/i.test(url)) return true;
        if (/katalyst-crm\.com\/objects\/[a-f0-9-]+/i.test(url)) return true;
        return false;
    }

    function buildInlineVideoEmbed(rawUrl) {
        const url = (rawUrl || '').trim();
        if (!url) return '';
        if (/^(javascript|data|vbscript):/i.test(url)) return '';
        if (isDirectNoteVideo(url, '')) return '';
        const drive = url.match(/(?:drive\.google\.com\/(?:file\/d\/|open\?id=)|docs\.google\.com\/file\/d\/)([a-zA-Z0-9_-]+)/i);
        if (drive) return `https://drive.google.com/file/d/${drive[1]}/preview`;
        const vimeo = url.match(/(?:vimeo\.com\/(?:video\/|channels\/[^/]+\/|groups\/[^/]+\/videos\/|album\/\d+\/video\/|ondemand\/[^/]+\/|manage\/videos\/)?|player\.vimeo\.com\/video\/)(\d+)/i);
        if (vimeo) return `https://player.vimeo.com/video/${vimeo[1]}`;
        const yt = url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{6,})/i);
        if (yt) return `https://www.youtube.com/embed/${yt[1]}`;
        if (/^https?:\/\//i.test(url)) return url;
        return '';
    }

    function renderNoteVideoFigure(data) {
        const raw = (data.url || data.embed_url || data.file_url || '').trim();
        if (!raw || /^(javascript|data|vbscript):/i.test(raw)) return '';
        const caption = escapeHtml(data.caption || '');
        const cap = caption ? `<figcaption class="text-sm text-gray-400 mt-2">${caption}</figcaption>` : '';
        if (isDirectNoteVideo(raw, data.source)) {
            return `<figure class="my-3"><video src="${escapeHtml(raw)}" controls playsinline preload="metadata" class="w-full rounded-lg border border-cyan-electric/20 bg-black"></video>${cap}</figure>`;
        }
        const embed = buildInlineVideoEmbed(raw);
        if (!embed) return '';
        return `<figure class="my-3"><div class="relative w-full rounded-lg overflow-hidden border border-cyan-electric/20" style="padding-bottom:56.25%;"><iframe src="${escapeHtml(embed)}" class="absolute inset-0 w-full h-full" allowfullscreen allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"></iframe></div>${cap}</figure>`;
    }

    function renderPreviewFromBlocks(blocks) {
        if (!Array.isArray(blocks) || !blocks.length) {
            return '<p class="text-gray-500 italic">No lesson notes yet.</p>';
        }
        return blocks.map(function (block) {
            if (!block || !block.type || !block.data) return '';
            const text = escapeHtml(block.data.text || '');
            if (block.type === 'header') {
                const level = Number(block.data.level) || 3;
                const safeLevel = Math.min(Math.max(level, 2), 4);
                return `<h${safeLevel}>${text}</h${safeLevel}>`;
            }
            if (block.type === 'paragraph') {
                return `<p>${text.replace(/\n/g, '<br>')}</p>`;
            }
            if (block.type === 'quote') {
                const caption = escapeHtml(block.data.caption || '');
                return `<blockquote>${text}${caption ? `<div class="text-xs text-gray-400 mt-2 not-italic">- ${caption}</div>` : ''}</blockquote>`;
            }
            if (block.type === 'list') {
                const items = Array.isArray(block.data.items) ? block.data.items : [];
                if (!items.length) return '';
                const listItems = items.map(function (item) { return `<li>${escapeHtml(item)}</li>`; }).join('');
                if ((block.data.style || 'unordered') === 'ordered') {
                    return `<ol>${listItems}</ol>`;
                }
                return `<ul>${listItems}</ul>`;
            }
            if (block.type === 'image') {
                const url = (block.data.file && block.data.file.url) || block.data.url || '';
                if (!url) return '';
                const caption = escapeHtml(block.data.caption || '');
                return `<figure class="my-3"><img src="${escapeHtml(url)}" alt="${caption || 'Lesson figure'}" class="w-full h-auto rounded-lg">${caption ? `<figcaption class="text-sm text-gray-400 mt-2">${caption}</figcaption>` : ''}</figure>`;
            }
            if (block.type === 'video') {
                return renderNoteVideoFigure(block.data || {});
            }
            return '';
        }).join('') || '<p class="text-gray-500 italic">No lesson notes yet.</p>';
    }

    function renderPreviewFromRaw(rawValue) {
        if (!rawValue || !String(rawValue).trim()) {
            return '<p class="text-gray-500 italic">No lesson notes yet.</p>';
        }
        try {
            return renderPreviewFromBlocks(parseContentBlocks(rawValue));
        } catch (error) {
            return '<p class="text-gray-500 italic">Lesson notes format is invalid. Please check JSON before saving.</p>';
        }
    }

    function normalizeBlock(block) {
        if (!block || typeof block !== 'object') {
            return { type: 'paragraph', data: { text: '' } };
        }
        const type = block.type || 'paragraph';
        const data = block.data || {};
        if (type === 'header') {
            return { type: 'header', data: { text: data.text || '', level: Number(data.level) || 2 } };
        }
        if (type === 'list') {
            return {
                type: 'list',
                data: {
                    style: (data.style || 'unordered') === 'ordered' ? 'ordered' : 'unordered',
                    items: Array.isArray(data.items) ? data.items : [],
                },
            };
        }
        if (type === 'quote') {
            return { type: 'quote', data: { text: data.text || '', caption: data.caption || '' } };
        }
        if (type === 'image') {
            const file = data.file && typeof data.file === 'object' ? data.file : {};
            return {
                type: 'image',
                data: {
                    file: { url: file.url || data.url || '' },
                    caption: data.caption || '',
                },
            };
        }
        if (type === 'video') {
            return {
                type: 'video',
                data: {
                    url: data.url || data.embed_url || data.file_url || '',
                    caption: data.caption || '',
                    source: data.source || '',
                },
            };
        }
        return { type: 'paragraph', data: { text: data.text || '' } };
    }

    function mount(root, options) {
        if (!root) return null;
        const opts = options || {};
        const uploadImageUrl = opts.uploadImageUrl || '';
        const uploadVideoUrl = opts.uploadVideoUrl || '';
        const saveNotesUrl = opts.saveNotesUrl || '';
        const doneLabel = opts.doneLabel || 'Done Editing Notes';
        const idleDoneHtml = '<i class="fas fa-check mr-1"></i> ' + doneLabel;
        const onPersist = typeof opts.onPersist === 'function' ? opts.onPersist : null;
        const toggleBtn = opts.toggleBtn || null;

        const displayEl = root.querySelector('[data-notes-display]');
        const editorEl = root.querySelector('[data-notes-editor]');
        const listEl = root.querySelector('[data-notes-block-list]');
        const inputEl = root.querySelector('[data-notes-input]');
        const feedbackEl = root.querySelector('[data-notes-feedback]');
        const doneButtons = function () { return root.querySelectorAll('[data-notes-done]'); };

        let blocks = [];
        if (Array.isArray(opts.initialBlocks)) {
            blocks = opts.initialBlocks.map(normalizeBlock);
        } else if (inputEl && inputEl.value) {
            blocks = parseContentBlocks(inputEl.value).map(normalizeBlock);
        }

        let uploadsInFlight = 0;
        let feedbackTimer = null;
        let destroyed = false;

        function isOpen() {
            return !!(editorEl && !editorEl.classList.contains('hidden'));
        }

        function updateDoneButtons() {
            const busy = uploadsInFlight > 0;
            doneButtons().forEach(function (btn) {
                btn.disabled = busy;
                btn.setAttribute('aria-busy', busy ? 'true' : 'false');
                btn.innerHTML = busy
                    ? '<i class="fas fa-circle-notch fa-spin mr-1"></i> Uploading…'
                    : idleDoneHtml;
            });
            if (toggleBtn && editorEl && isOpen()) {
                toggleBtn.disabled = busy;
                toggleBtn.innerHTML = busy
                    ? '<i class="fas fa-circle-notch fa-spin mr-1"></i> Uploading…'
                    : '<i class="fas fa-check mr-1"></i> Done';
            }
        }

        function beginUpload() {
            uploadsInFlight += 1;
            updateDoneButtons();
        }

        function endUpload() {
            uploadsInFlight = Math.max(0, uploadsInFlight - 1);
            updateDoneButtons();
        }

        function showFeedback(label, alreadyMessage) {
            if (!feedbackEl) return;
            feedbackEl.textContent = alreadyMessage ? label : (label + ' added — it’s highlighted below.');
            feedbackEl.classList.add('show');
            if (feedbackTimer) clearTimeout(feedbackTimer);
            feedbackTimer = setTimeout(function () {
                feedbackEl.classList.remove('show');
            }, 2200);
        }

        function sync() {
            if (inputEl) {
                inputEl.value = JSON.stringify({ blocks: blocks }, null, 2);
            }
            if (displayEl) {
                displayEl.innerHTML = renderPreviewFromBlocks(blocks);
            }
        }

        function setDoneButtonsSaving(saving) {
            doneButtons().forEach(function (btn) {
                btn.disabled = saving;
                btn.innerHTML = saving
                    ? '<i class="fas fa-circle-notch fa-spin mr-1"></i> Saving notes…'
                    : idleDoneHtml;
            });
        }

        async function persist() {
            sync();
            if (!saveNotesUrl) {
                if (onPersist) onPersist(blocks);
                return true;
            }
            try {
                const resp = await fetch(saveNotesUrl, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': getCsrfToken(),
                        'Content-Type': 'application/json',
                    },
                    credentials: 'same-origin',
                    body: JSON.stringify({ blocks: blocks }),
                });
                const payload = await resp.json().catch(function () { return {}; });
                if (!resp.ok || !payload.ok) {
                    throw new Error(payload.error || payload.detail || 'Could not save notes');
                }
                if (onPersist) onPersist(blocks);
                return true;
            } catch (err) {
                showFeedback(err.message || 'Could not save notes', true);
                return false;
            }
        }

        async function setOpen(opening) {
            if (!editorEl) return false;
            if (!opening && uploadsInFlight > 0) {
                updateDoneButtons();
                return false;
            }
            if (!opening) {
                setDoneButtonsSaving(true);
                const saved = await persist();
                setDoneButtonsSaving(false);
                if (!saved) return false;
            }
            editorEl.classList.toggle('hidden', !opening);
            if (displayEl) displayEl.classList.toggle('hidden', opening);
            if (inputEl) inputEl.classList.add('hidden');
            if (toggleBtn) {
                toggleBtn.disabled = false;
                toggleBtn.innerHTML = opening
                    ? '<i class="fas fa-check mr-1"></i> Done'
                    : '<i class="fas fa-edit mr-1"></i> Edit';
            }
            if (!opening && displayEl) {
                displayEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
            return true;
        }

        function renderEditor() {
            if (!listEl) return;
            listEl.innerHTML = '';
            if (!blocks.length) {
                listEl.innerHTML = '<p class="text-sm text-gray-500 italic">No blocks yet. Add your first paragraph or heading.</p>';
                return;
            }

            blocks.forEach(function (block, index) {
                const card = document.createElement('div');
                card.className = 'notes-editor-card';

                let bodyHtml = '';
                if (block.type === 'header') {
                    bodyHtml = `
                        <label class="notes-editor-label">Header level</label>
                        <select data-role="header-level" class="w-full bg-[#0a0e27]/40 border border-cyan-electric/20 rounded-lg px-3 py-2 text-sm mb-3">
                            <option value="2" ${Number(block.data.level) === 2 ? 'selected' : ''}>H2</option>
                            <option value="3" ${Number(block.data.level) === 3 ? 'selected' : ''}>H3</option>
                            <option value="4" ${Number(block.data.level) === 4 ? 'selected' : ''}>H4</option>
                        </select>
                        <label class="notes-editor-label">Header text</label>
                        <input data-role="header-text" type="text" value="${escapeHtml(block.data.text || '')}" class="w-full bg-[#0a0e27]/40 border border-cyan-electric/20 rounded-lg px-3 py-2 text-sm" />
                    `;
                } else if (block.type === 'list') {
                    bodyHtml = `
                        <label class="notes-editor-label">List style</label>
                        <select data-role="list-style" class="w-full bg-[#0a0e27]/40 border border-cyan-electric/20 rounded-lg px-3 py-2 text-sm mb-3">
                            <option value="unordered" ${(block.data.style || 'unordered') === 'unordered' ? 'selected' : ''}>Bulleted</option>
                            <option value="ordered" ${(block.data.style || 'unordered') === 'ordered' ? 'selected' : ''}>Numbered</option>
                        </select>
                        <label class="notes-editor-label">List items (one item per line)</label>
                        <textarea data-role="list-items" rows="4" class="w-full bg-[#0a0e27]/40 border border-cyan-electric/20 rounded-lg px-3 py-2 text-sm resize-y">${escapeHtml((block.data.items || []).join('\n'))}</textarea>
                    `;
                } else if (block.type === 'quote') {
                    bodyHtml = `
                        <label class="notes-editor-label">Quote text</label>
                        <textarea data-role="quote-text" rows="3" class="w-full bg-[#0a0e27]/40 border border-cyan-electric/20 rounded-lg px-3 py-2 text-sm resize-y mb-3">${escapeHtml(block.data.text || '')}</textarea>
                        <label class="notes-editor-label">Caption (optional)</label>
                        <input data-role="quote-caption" type="text" value="${escapeHtml(block.data.caption || '')}" class="w-full bg-[#0a0e27]/40 border border-cyan-electric/20 rounded-lg px-3 py-2 text-sm" />
                    `;
                } else if (block.type === 'image') {
                    const imageUrl = (block.data.file && block.data.file.url) || block.data.url || '';
                    bodyHtml = `
                        ${imageUrl ? `<img data-role="image-preview" src="${escapeHtml(imageUrl)}" alt="" class="w-full h-auto rounded-lg mb-3">` : '<p data-role="image-missing" class="text-sm text-gray-500 mb-3">No image yet — paste a URL or upload a file.</p>'}
                        <label class="notes-editor-label">Image URL</label>
                        <input data-role="image-url" type="url" value="${escapeHtml(imageUrl)}" placeholder="https://…" class="w-full bg-[#0a0e27]/40 border border-cyan-electric/20 rounded-lg px-3 py-2 text-sm mb-3" />
                        <label class="notes-editor-label">Upload image</label>
                        <input data-role="image-file" type="file" accept="image/png,image/jpeg,image/webp,image/gif" class="w-full text-sm text-gray-300 mb-2" />
                        <p data-role="image-upload-status" class="text-xs text-gray-500 mb-3 hidden"></p>
                        <label class="notes-editor-label">Caption (optional)</label>
                        <input data-role="image-caption" type="text" value="${escapeHtml(block.data.caption || '')}" class="w-full bg-[#0a0e27]/40 border border-cyan-electric/20 rounded-lg px-3 py-2 text-sm" />
                    `;
                } else if (block.type === 'video') {
                    const videoUrl = block.data.url || '';
                    const isFile = isDirectNoteVideo(videoUrl, block.data.source);
                    const embed = isFile ? '' : buildInlineVideoEmbed(videoUrl);
                    bodyHtml = `
                        ${isFile ? `<video data-role="video-file-preview" src="${escapeHtml(videoUrl)}" controls playsinline preload="metadata" class="w-full rounded-lg border border-cyan-electric/20 mb-3 bg-black"></video>` : (embed ? `<div class="relative w-full rounded-lg overflow-hidden border border-cyan-electric/20 mb-3" style="padding-bottom:56.25%;"><iframe data-role="video-preview" src="${escapeHtml(embed)}" class="absolute inset-0 w-full h-full" allowfullscreen allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"></iframe></div>` : '<p class="text-sm text-gray-500 mb-3">Upload a video (we convert it to WebM) or paste a Vimeo, YouTube, or Google Drive URL.</p>')}
                        <label class="notes-editor-label">Upload video</label>
                        <input data-role="video-file" type="file" accept="video/mp4,video/webm,video/quicktime,video/*" class="w-full text-sm text-gray-300 mb-2" />
                        <p data-role="video-upload-status" class="text-xs text-gray-500 mb-3 hidden"></p>
                        <label class="notes-editor-label">Video URL</label>
                        <input data-role="video-url" type="url" value="${escapeHtml(videoUrl)}" placeholder="https://vimeo.com/… or Drive / YouTube embed" class="w-full bg-[#0a0e27]/40 border border-cyan-electric/20 rounded-lg px-3 py-2 text-sm mb-3" />
                        <label class="notes-editor-label">Caption (optional)</label>
                        <input data-role="video-caption" type="text" value="${escapeHtml(block.data.caption || '')}" class="w-full bg-[#0a0e27]/40 border border-cyan-electric/20 rounded-lg px-3 py-2 text-sm" />
                    `;
                } else {
                    bodyHtml = `
                        <label class="notes-editor-label">Paragraph text</label>
                        <textarea data-role="paragraph-text" rows="4" class="w-full bg-[#0a0e27]/40 border border-cyan-electric/20 rounded-lg px-3 py-2 text-sm resize-y">${escapeHtml(block.data.text || '')}</textarea>
                    `;
                }

                card.innerHTML = `
                    <div class="flex items-center justify-between gap-2 mb-3">
                        <span class="text-xs font-semibold px-2 py-1 rounded-full bg-cyan-electric/15 border border-cyan-electric/30 uppercase">${escapeHtml(block.type)}</span>
                        <div class="flex gap-2">
                            <button type="button" data-action="up" class="px-2 py-1 text-xs border border-cyan-electric/30 rounded hover:bg-cyan-electric/20">Up</button>
                            <button type="button" data-action="down" class="px-2 py-1 text-xs border border-cyan-electric/30 rounded hover:bg-cyan-electric/20">Down</button>
                            <button type="button" data-action="delete" class="px-2 py-1 text-xs border border-red-400/50 text-red-300 rounded hover:bg-red-500/10">Delete</button>
                        </div>
                    </div>
                    ${bodyHtml}
                `;

                card.querySelectorAll('button[data-action]').forEach(function (btn) {
                    btn.addEventListener('click', function () {
                        const action = this.dataset.action;
                        if (action === 'delete') {
                            blocks.splice(index, 1);
                        } else if (action === 'up' && index > 0) {
                            const tmp = blocks[index - 1];
                            blocks[index - 1] = blocks[index];
                            blocks[index] = tmp;
                        } else if (action === 'down' && index < blocks.length - 1) {
                            const tmp = blocks[index + 1];
                            blocks[index + 1] = blocks[index];
                            blocks[index] = tmp;
                        }
                        sync();
                        renderEditor();
                    });
                });

                function bindInput(selector, cb) {
                    const el = card.querySelector(selector);
                    if (!el) return;
                    el.addEventListener('input', function () {
                        cb(this.value);
                        sync();
                    });
                    if (el.tagName === 'SELECT') {
                        el.addEventListener('change', function () {
                            cb(this.value);
                            sync();
                        });
                    }
                }

                bindInput('[data-role="paragraph-text"]', function (value) { blocks[index].data.text = value; });
                bindInput('[data-role="header-text"]', function (value) { blocks[index].data.text = value; });
                bindInput('[data-role="header-level"]', function (value) { blocks[index].data.level = Number(value) || 2; });
                bindInput('[data-role="list-style"]', function (value) {
                    blocks[index].data.style = value === 'ordered' ? 'ordered' : 'unordered';
                });
                bindInput('[data-role="list-items"]', function (value) {
                    blocks[index].data.items = value.split('\n').map(function (item) { return item.trim(); }).filter(Boolean);
                });
                bindInput('[data-role="quote-text"]', function (value) { blocks[index].data.text = value; });
                bindInput('[data-role="quote-caption"]', function (value) { blocks[index].data.caption = value; });
                bindInput('[data-role="image-caption"]', function (value) { blocks[index].data.caption = value; });
                bindInput('[data-role="image-url"]', function (value) {
                    if (!blocks[index].data.file) blocks[index].data.file = {};
                    blocks[index].data.file.url = value;
                    const preview = card.querySelector('[data-role="image-preview"]');
                    const missing = card.querySelector('[data-role="image-missing"]');
                    if (preview) {
                        preview.src = value;
                        preview.classList.toggle('hidden', !value);
                    } else if (value) {
                        renderEditor();
                        return;
                    }
                    if (missing) missing.classList.toggle('hidden', !!value);
                });
                bindInput('[data-role="video-url"]', function (value) {
                    blocks[index].data.url = value;
                    if (!isDirectNoteVideo(value, blocks[index].data.source)) {
                        blocks[index].data.source = '';
                    }
                    const filePreview = card.querySelector('[data-role="video-file-preview"]');
                    const iframe = card.querySelector('[data-role="video-preview"]');
                    const embed = buildInlineVideoEmbed(value);
                    if (isDirectNoteVideo(value, blocks[index].data.source) && filePreview) {
                        filePreview.src = value;
                    } else if (iframe && embed) {
                        iframe.src = embed;
                    } else {
                        renderEditor();
                    }
                });
                bindInput('[data-role="video-caption"]', function (value) { blocks[index].data.caption = value; });

                const videoFileInput = card.querySelector('[data-role="video-file"]');
                if (videoFileInput) {
                    videoFileInput.addEventListener('change', async function () {
                        const file = this.files && this.files[0];
                        if (!file) return;
                        const statusEl = card.querySelector('[data-role="video-upload-status"]');
                        if (statusEl) {
                            statusEl.textContent = 'Converting to WebM and uploading… this can take a minute.';
                            statusEl.classList.remove('hidden', 'text-red-300', 'text-emerald-300');
                            statusEl.classList.add('text-gray-400');
                        }
                        const formData = new FormData();
                        formData.append('video', file);
                        beginUpload();
                        try {
                            const resp = await fetch(uploadVideoUrl, {
                                method: 'POST',
                                headers: { 'X-CSRFToken': getCsrfToken() },
                                body: formData,
                                credentials: 'same-origin',
                            });
                            const payload = await resp.json().catch(function () { return {}; });
                            if (!resp.ok || !payload.url) {
                                throw new Error(payload.error || 'Upload failed');
                            }
                            blocks[index].data.url = payload.url;
                            blocks[index].data.source = payload.source || 'upload';
                            sync();
                            renderEditor();
                            persist();
                        } catch (err) {
                            if (statusEl) {
                                statusEl.textContent = err.message || 'Upload failed';
                                statusEl.classList.remove('text-gray-400', 'text-emerald-300');
                                statusEl.classList.add('text-red-300');
                            }
                        } finally {
                            endUpload();
                        }
                    });
                }

                const imageFileInput = card.querySelector('[data-role="image-file"]');
                if (imageFileInput) {
                    imageFileInput.addEventListener('change', async function () {
                        const file = this.files && this.files[0];
                        if (!file) return;
                        const statusEl = card.querySelector('[data-role="image-upload-status"]');
                        if (statusEl) {
                            statusEl.textContent = 'Uploading…';
                            statusEl.classList.remove('hidden', 'text-red-300', 'text-emerald-300');
                            statusEl.classList.add('text-gray-400');
                        }
                        const formData = new FormData();
                        formData.append('image', file);
                        beginUpload();
                        try {
                            const resp = await fetch(uploadImageUrl, {
                                method: 'POST',
                                headers: { 'X-CSRFToken': getCsrfToken() },
                                body: formData,
                                credentials: 'same-origin',
                            });
                            const payload = await resp.json().catch(function () { return {}; });
                            if (!resp.ok || !payload.url) {
                                throw new Error(payload.error || 'Upload failed');
                            }
                            if (!blocks[index].data.file) blocks[index].data.file = {};
                            blocks[index].data.file.url = payload.url;
                            sync();
                            renderEditor();
                            persist();
                        } catch (err) {
                            if (statusEl) {
                                statusEl.textContent = err.message || 'Upload failed';
                                statusEl.classList.remove('text-gray-400', 'text-emerald-300');
                                statusEl.classList.add('text-red-300');
                            }
                        } finally {
                            endUpload();
                        }
                    });
                }

                listEl.appendChild(card);
            });
        }

        function addBlock(type) {
            const presets = {
                paragraph: { type: 'paragraph', data: { text: '' } },
                header: { type: 'header', data: { text: '', level: 2 } },
                list: { type: 'list', data: { style: 'unordered', items: [] } },
                quote: { type: 'quote', data: { text: '', caption: '' } },
                image: { type: 'image', data: { file: { url: '' }, caption: '' } },
                video: { type: 'video', data: { url: '', caption: '' } },
            };
            blocks.push(presets[type] || presets.paragraph);
            sync();
            renderEditor();
            const labels = {
                paragraph: 'Paragraph',
                header: 'Header',
                list: 'List',
                quote: 'Quote',
                image: 'Image',
                video: 'Video',
            };
            showFeedback(labels[type] || 'Block');
            const cards = listEl ? listEl.querySelectorAll('.notes-editor-card') : [];
            const last = cards[cards.length - 1];
            if (last) {
                last.classList.add('notes-editor-card-just-added');
                last.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                setTimeout(function () { last.classList.remove('notes-editor-card-just-added'); }, 1600);
            }
        }

        root.querySelectorAll('[data-add-block]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                addBlock(this.getAttribute('data-add-block'));
            });
        });
        doneButtons().forEach(function (btn) {
            btn.addEventListener('click', async function () {
                if (opts.keepOpenOnDone) {
                    setDoneButtonsSaving(true);
                    const saved = await persist();
                    setDoneButtonsSaving(false);
                    if (saved) showFeedback('Saved', true);
                    return;
                }
                await setOpen(false);
            });
        });

        sync();
        renderEditor();
        if (opts.startOpen) {
            if (editorEl) editorEl.classList.remove('hidden');
            if (displayEl) displayEl.classList.add('hidden');
            if (toggleBtn) {
                toggleBtn.innerHTML = '<i class="fas fa-check mr-1"></i> Done';
            }
        }
        updateDoneButtons();

        return {
            getBlocks: function () { return blocks; },
            persist: persist,
            setOpen: setOpen,
            isOpen: isOpen,
            isBusy: function () { return uploadsInFlight > 0; },
            destroy: function () {
                destroyed = true;
                if (feedbackTimer) clearTimeout(feedbackTimer);
            },
        };
    }

    global.CourseforgeNotesEditor = {
        mount: mount,
        escapeHtml: escapeHtml,
        parseBlocks: parseContentBlocks,
        renderPreview: renderPreviewFromRaw,
        renderPreviewFromBlocks: renderPreviewFromBlocks,
    };
})(window);
