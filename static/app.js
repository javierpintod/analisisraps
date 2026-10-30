/**
 * SENA - Sistema de Análisis de Avance por RAPs
 * Controlador Frontend Interactivo con Soporte Integral Multi-Ficha
 */

document.addEventListener("DOMContentLoaded", () => {
    // Estado global de la aplicación
    let multiAnalysisData = null;      // Respuesta completa del servidor
    let activeFichaId = "ALL";         // 'ALL' para consolidado, o ID de la ficha seleccionada
    let selectedStates = new Set();
    let currentRapFilter = "all";
    let currentAprFilter = "all";

    // Elementos del DOM
    const dropZone = document.getElementById("drop-zone");
    const fileInput = document.getElementById("file-input");
    const fileInfo = document.getElementById("file-info");
    const fileNameText = document.getElementById("file-name-text");
    const btnClearFile = document.getElementById("btn-clear-file");
    const btnLoadSample = document.getElementById("btn-load-sample");
    const btnExportExcel = document.getElementById("btn-export-excel");
    const emptyState = document.getElementById("empty-state");
    const dashboardContent = document.getElementById("dashboard-content");
    const controlsBar = document.getElementById("controls-bar");
    const stateChipsContainer = document.getElementById("state-chips");
    const btnApplyFilters = document.getElementById("btn-apply-filters");
    const inputUmbralVerde = document.getElementById("input-umbral-verde");
    const inputUmbralAmarillo = document.getElementById("input-umbral-amarillo");

    // Multi-Ficha Navigator
    const fichasNavContainer = document.getElementById("fichas-nav-container");
    const fichasCountBadge = document.getElementById("fichas-count-badge");
    const fichasPillsRow = document.getElementById("fichas-pills-row");
    const tabBtnFichas = document.getElementById("tab-btn-fichas");
    const tabFichas = document.getElementById("tab-fichas");

    // Modal
    const modalBackdrop = document.getElementById("modal-backdrop");
    const btnCloseModal = document.getElementById("btn-close-modal");
    const modalAprName = document.getElementById("modal-apr-name");
    const modalAprDoc = document.getElementById("modal-apr-doc");
    const modalAprContent = document.getElementById("modal-apr-content");

    // Toast
    const toast = document.getElementById("toast");

    function showToast(message, isError = false) {
        toast.textContent = message;
        toast.style.background = isError ? "#EF4444" : "#1F2937";
        toast.style.borderColor = isError ? "#DC2626" : "rgba(57, 169, 0, 0.4)";
        toast.style.display = "block";
        setTimeout(() => {
            toast.style.display = "none";
        }, 3500);
    }

    // -------------------------------------------------------------
    // EVENTOS DE SUBIDA DE ARCHIVO (DRAG & DROP Y MULTI-ARCHIVO)
    // -------------------------------------------------------------
    dropZone.addEventListener("click", () => fileInput.click());

    ["dragenter", "dragover"].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropZone.classList.add("dragover");
        });
    });

    ["dragleave", "drop"].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropZone.classList.remove("dragover");
        });
    });

    dropZone.addEventListener("drop", (e) => {
        const files = e.dataTransfer.files;
        if (files && files.length > 0) {
            handleMultipleFilesUpload(Array.from(files));
        }
    });

    fileInput.addEventListener("change", (e) => {
        const files = e.target.files;
        if (files && files.length > 0) {
            handleMultipleFilesUpload(Array.from(files));
        }
    });

    btnClearFile.addEventListener("click", (e) => {
        e.stopPropagation();
        resetAppState();
    });

    function resetAppState() {
        fileInput.value = "";
        multiAnalysisData = null;
        activeFichaId = "ALL";
        fileInfo.style.display = "none";
        emptyState.style.display = "flex";
        dashboardContent.style.display = "none";
        controlsBar.style.display = "none";
        btnExportExcel.disabled = true;
    }

    async function handleMultipleFilesUpload(filesList) {
        if (!filesList || filesList.length === 0) return;

        showToast(`Procesando ${filesList.length} archivo(s) de formación...`);
        fileNameText.textContent = filesList.length === 1 
            ? filesList[0].name 
            : `${filesList.length} archivos de fichas seleccionados`;
        fileInfo.style.display = "inline-flex";

        try {
            // Leer todos los archivos en base64 en paralelo
            const payloadFiles = await Promise.all(filesList.map(async (file) => {
                const b64 = await readFileAsBase64(file);
                return { filename: file.name, content_base64: b64 };
            }));

            const res = await fetch("/api/upload", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ files: payloadFiles })
            });

            const data = await res.json();
            if (!data.success) {
                throw new Error(data.error || "Error al procesar los archivos");
            }

            setupStateChips(data.states);
            setMultiAnalysisData(data.analysis);
            showToast(`¡${data.total_fichas} Ficha(s) analizada(s) exitosamente!`);
        } catch (err) {
            console.error(err);
            showToast(err.message, true);
        }
    }

    function readFileAsBase64(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => {
                const result = reader.result;
                const base64 = result.split(",")[1];
                resolve(base64);
            };
            reader.onerror = error => reject(error);
            reader.readAsDataURL(file);
        });
    }

    // -------------------------------------------------------------
    // CARGAR ARCHIVO DE MUESTRA (DEMO MULTI-FICHA)
    // -------------------------------------------------------------
    async function loadSampleData(showNotification = true) {
        if (showNotification) showToast("Cargando fichas de formación SENA...");
        try {
            const res = await fetch("/api/sample");
            const data = await res.json();
            if (!data.success) {
                throw new Error(data.error || "No se pudo cargar la muestra");
            }

            fileNameText.textContent = `${data.total_fichas} Fichas Activas (Ficha 3239137 + Ficha 2714589)`;
            fileInfo.style.display = "inline-flex";

            setupStateChips(data.states);
            setMultiAnalysisData(data.analysis);
            if (showNotification) showToast("Múltiples Fichas cargadas con éxito");
        } catch (err) {
            console.error(err);
            if (showNotification) showToast(err.message, true);
        }
    }

    btnLoadSample.addEventListener("click", () => loadSampleData(true));

    // -------------------------------------------------------------
    // GESTIÓN DE DATOS MULTI-FICHA Y NAVEGACIÓN
    // -------------------------------------------------------------
    function setMultiAnalysisData(analysis) {
        multiAnalysisData = analysis;
        activeFichaId = "ALL";

        emptyState.style.display = "none";
        dashboardContent.style.display = "block";
        btnExportExcel.disabled = false;

        renderFichasNavigator(analysis.fichas_selector, analysis.total_fichas);
        renderCurrentView();
    }

    function renderFichasNavigator(selectorList, totalFichas) {
        fichasPillsRow.innerHTML = "";
        fichasCountBadge.textContent = `${totalFichas} Ficha(s) en Análisis`;

        selectorList.forEach(item => {
            const pill = document.createElement("button");
            pill.type = "button";
            pill.className = `ficha-pill ${item.id === activeFichaId ? 'active' : ''}`;
            
            const badgeColor = item.id === "ALL" ? "" : (item.avance >= 80 ? "color: var(--color-green);" : (item.avance >= 50 ? "color: var(--color-amber);" : "color: var(--color-red);"));
            
            pill.innerHTML = `
                <span>${escapeHtml(item.label)}</span>
                <span class="pill-badge" style="${badgeColor}">${item.avance}%</span>
            `;

            pill.addEventListener("click", () => {
                activeFichaId = item.id;
                document.querySelectorAll(".ficha-pill").forEach(p => p.classList.remove("active"));
                pill.classList.add("active");
                renderCurrentView();
            });

            fichasPillsRow.appendChild(pill);
        });
    }

    // Renderiza la vista según la ficha activa ('ALL' para consolidado o ID específico)
    function renderCurrentView() {
        if (!multiAnalysisData) return;

        const isConsolidado = (activeFichaId === "ALL");
        const currentData = isConsolidado 
            ? multiAnalysisData.consolidado 
            : multiAnalysisData.detalle_fichas[activeFichaId];

        if (!currentData) return;

        // Banner
        document.getElementById("kpi-tag-context").textContent = isConsolidado ? "Consolidado de Centro" : `Ficha ${currentData.meta.ficha}`;
        document.getElementById("meta-ficha").textContent = currentData.meta.ficha;
        document.getElementById("meta-programa").textContent = currentData.meta.programa;
        document.getElementById("meta-aprendices").textContent = `${currentData.meta.total_aprendices_analizados} Aprendices`;
        document.getElementById("meta-raps").textContent = isConsolidado 
            ? `${currentData.meta.total_raps} RAPs Totales` 
            : `${currentData.meta.total_raps} RAPs`;

        // KPIs
        const kpis = currentData.kpis;
        const pctAvance = kpis.porcentaje_avance_real;

        document.getElementById("kpi-avance-real").textContent = `${pctAvance}%`;
        document.getElementById("kpi-evaluaciones-detalle").textContent = 
            `${kpis.total_aprobados.toLocaleString()} / ${kpis.total_evaluaciones_posibles.toLocaleString()} juicios aprobados`;

        // Anillo Radial SVG (perímetro 314.15)
        const gaugeCircle = document.getElementById("gauge-fill-circle");
        const gaugeText = document.getElementById("gauge-text");
        const circumference = 314.15;
        const offset = circumference - (pctAvance / 100) * circumference;
        gaugeCircle.style.strokeDashoffset = Math.max(0, offset);
        gaugeText.textContent = `${Math.round(pctAvance)}%`;

        // Eficacia
        document.getElementById("kpi-eficacia").textContent = `${kpis.porcentaje_aprobacion_evaluados}%`;
        document.getElementById("bar-eficacia").style.width = `${Math.min(100, kpis.porcentaje_aprobacion_evaluados)}%`;
        document.getElementById("kpi-eficacia-sub").textContent = 
            `${kpis.total_aprobados} Aprobados vs ${kpis.total_deficientes} Deficientes`;

        // Cobertura
        document.getElementById("kpi-cobertura").textContent = `${kpis.porcentaje_cobertura_evaluativa}%`;
        document.getElementById("bar-cobertura").style.width = `${Math.min(100, kpis.porcentaje_cobertura_evaluativa)}%`;
        document.getElementById("kpi-cobertura-sub").textContent = 
            `${(kpis.total_aprobados + kpis.total_deficientes)} con juicio, ${kpis.total_por_evaluar} pendientes`;

        // Semáforo RAPs Pills
        document.getElementById("count-raps-criticos").textContent = kpis.raps_criticos;
        document.getElementById("count-raps-avance").textContent = kpis.raps_en_avance;
        document.getElementById("count-raps-optimos").textContent = kpis.raps_optimos;

        // Gestión de visibilidad de pestañas
        if (isConsolidado) {
            tabBtnFichas.style.display = "flex";
            document.getElementById("tab-count-fichas").textContent = multiAnalysisData.total_fichas;
            renderComparativeTable(multiAnalysisData.consolidado.tabla_fichas);

            // En vista consolidada, activar la pestaña de Ranking de Fichas
            switchTab("tab-fichas");
        } else {
            tabBtnFichas.style.display = "none";
            // En vista de ficha específica, mostrar el semáforo de RAPs
            switchTab("tab-raps");
        }

        // Renderizado de las secciones detalladas
        const rapsParaMostrar = isConsolidado 
            ? (currentData.raps.length > 0 ? currentData.raps : Object.values(multiAnalysisData.detalle_fichas)[0].raps)
            : currentData.raps;

        document.getElementById("tab-count-raps").textContent = rapsParaMostrar.length;
        document.getElementById("tab-count-apr").textContent = currentData.aprendices.length;

        renderRapsList(rapsParaMostrar);
        renderAprendicesTable(currentData.aprendices, isConsolidado);
        renderCompetenciasGrid(currentData.competencias.length > 0 ? currentData.competencias : Object.values(multiAnalysisData.detalle_fichas)[0].competencias);
        renderMatrix(currentData.matriz.filas.length > 0 ? currentData.matriz : Object.values(multiAnalysisData.detalle_fichas)[0].matriz);
    }

    function switchTab(tabId) {
        document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
        document.querySelectorAll(".tab-content").forEach(tc => tc.classList.remove("active"));

        const targetBtn = document.querySelector(`.tab-btn[data-tab="${tabId}"]`);
        const targetContent = document.getElementById(tabId);
        if (targetBtn) targetBtn.classList.add("active");
        if (targetContent) targetContent.classList.add("active");
    }

    // -------------------------------------------------------------
    // PESTAÑA CONSOLIDADA: TABLA COMPARATIVA DE FICHAS
    // -------------------------------------------------------------
    function renderComparativeTable(tablaFichas) {
        const tbody = document.getElementById("tbody-fichas-comparativo");
        tbody.innerHTML = "";

        const searchTerm = document.getElementById("search-ficha") ? document.getElementById("search-ficha").value.toLowerCase().trim() : "";

        const filtered = tablaFichas.filter(f => {
            return !searchTerm || 
                f.ficha.toLowerCase().includes(searchTerm) || 
                f.programa.toLowerCase().includes(searchTerm);
        });

        filtered.forEach(f => {
            const tr = document.createElement("tr");
            const fillClass = f.semaforo_cod === "optimo" ? "fill-green" : (f.semaforo_cod === "en_avance" ? "fill-amber" : "fill-red");
            const badgeClass = f.semaforo_cod === "optimo" ? "status-optimo" : (f.semaforo_cod === "en_avance" ? "status-avance" : "status-critico");

            tr.innerHTML = `
                <td style="font-weight: 700; color: #FFFFFF;">${escapeHtml(f.ficha)}</td>
                <td style="max-width: 280px; font-size: 0.8rem;">${escapeHtml(f.programa)}</td>
                <td style="text-align: center; font-weight: 600;">${f.total_aprendices}</td>
                <td style="text-align: center;">${f.total_raps}</td>
                <td>
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <div class="kpi-progress-bar" style="width: 70px; margin-bottom: 0;">
                            <div class="progress-fill ${fillClass}" style="width: ${f.porcentaje_avance}%"></div>
                        </div>
                        <span style="font-weight: 700;">${f.porcentaje_avance}%</span>
                    </div>
                </td>
                <td style="text-align: center; color: var(--color-green); font-weight: 600;">${f.porcentaje_aprobacion}%</td>
                <td style="text-align: center; color: var(--color-blue);">${f.porcentaje_cobertura}%</td>
                <td style="text-align: center; color: ${f.raps_criticos > 0 ? 'var(--color-red)' : 'var(--text-muted)'}; font-weight: 600;">${f.raps_criticos}</td>
                <td style="text-align: center; color: ${f.aprendices_riesgo > 0 ? 'var(--color-red)' : 'var(--text-muted)'}; font-weight: 600;">${f.aprendices_riesgo}</td>
                <td><span class="status-badge ${badgeClass}">${f.semaforo}</span></td>
                <td>
                    <button class="btn-inspect-ficha" data-ficha-id="${f.id}">Inspeccionar Ficha</button>
                </td>
            `;
            tbody.appendChild(tr);
        });

        // Eventos para inspeccionar ficha individual
        tbody.querySelectorAll(".btn-inspect-ficha").forEach(btn => {
            btn.addEventListener("click", () => {
                const fid = btn.dataset.fichaId;
                activeFichaId = fid;
                document.querySelectorAll(".ficha-pill").forEach(p => p.classList.remove("active"));
                const pillToActivate = Array.from(document.querySelectorAll(".ficha-pill")).find(p => p.textContent.includes(fid));
                if (pillToActivate) pillToActivate.classList.add("active");
                renderCurrentView();
            });
        });
    }

    if (document.getElementById("search-ficha")) {
        document.getElementById("search-ficha").addEventListener("input", () => {
            if (multiAnalysisData && multiAnalysisData.consolidado.tabla_fichas) {
                renderComparativeTable(multiAnalysisData.consolidado.tabla_fichas);
            }
        });
    }

    // -------------------------------------------------------------
    // PESTAÑA: SEMÁFORO DE RAPS
    // -------------------------------------------------------------
    function renderRapsList(raps) {
        const container = document.getElementById("raps-list-container");
        container.innerHTML = "";

        const searchTerm = document.getElementById("search-rap").value.toLowerCase().trim();

        const filtered = raps.filter(r => {
            const matchesCategory = currentRapFilter === "all" || r.categoria_cod === currentRapFilter;
            const matchesSearch = !searchTerm || 
                r.rap.toLowerCase().includes(searchTerm) || 
                r.competencia.toLowerCase().includes(searchTerm) ||
                (r.instructor && r.instructor.toLowerCase().includes(searchTerm));
            return matchesCategory && matchesSearch;
        });

        if (filtered.length === 0) {
            container.innerHTML = `<div style="text-align:center; padding: 2rem; color: var(--text-muted);">No se encontraron RAPs con los filtros seleccionados.</div>`;
            return;
        }

        filtered.forEach(r => {
            const card = document.createElement("div");
            card.className = `rap-item-card ${r.categoria_cod}`;

            const fillClass = r.categoria_cod === "optimo" ? "fill-green" : (r.categoria_cod === "en_avance" ? "fill-amber" : "fill-red");
            const badgeClass = r.categoria_cod === "optimo" ? "status-optimo" : (r.categoria_cod === "en_avance" ? "status-avance" : "status-critico");

            card.innerHTML = `
                <div>
                    <div class="rap-comp-name">${escapeHtml(r.competencia)}</div>
                    <div class="rap-title">${escapeHtml(r.rap)}</div>
                    <div class="rap-instructor">👨‍🏫 Instructor Evaluador: <strong>${escapeHtml(r.instructor || 'Por asignar')}</strong></div>
                </div>
                <div class="rap-progress-col">
                    <div class="rap-stats-header">
                        <span>Avance del Grupo</span>
                        <span>${r.porcentaje_aprobado}%</span>
                    </div>
                    <div class="kpi-progress-bar">
                        <div class="progress-fill ${fillClass}" style="width: ${r.porcentaje_aprobado}%"></div>
                    </div>
                    <div class="rap-stats-pills">
                        <span>🟢 ${r.aprobados} Aprobados</span>
                        <span>🔴 ${r.deficientes} Deficientes</span>
                        <span>⚪ ${r.pendientes} Pendientes</span>
                    </div>
                </div>
                <div class="rap-status-col">
                    <span class="status-badge ${badgeClass}">${r.semaforo}</span>
                    <span style="font-size: 0.75rem; color: var(--text-muted);">${r.aprobados} de ${r.aprobados + r.deficientes + r.pendientes} aprendices</span>
                </div>
            `;
            container.appendChild(card);
        });
    }

    document.getElementById("search-rap").addEventListener("input", () => {
        if (multiAnalysisData) {
            const currentData = activeFichaId === "ALL" 
                ? Object.values(multiAnalysisData.detalle_fichas)[0] 
                : multiAnalysisData.detalle_fichas[activeFichaId];
            renderRapsList(currentData.raps);
        }
    });

    document.querySelectorAll("#rap-status-filter .filter-chip").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll("#rap-status-filter .filter-chip").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentRapFilter = btn.dataset.filter;
            if (multiAnalysisData) {
                const currentData = activeFichaId === "ALL" 
                    ? Object.values(multiAnalysisData.detalle_fichas)[0] 
                    : multiAnalysisData.detalle_fichas[activeFichaId];
                renderRapsList(currentData.raps);
            }
        });
    });

    // -------------------------------------------------------------
    // PESTAÑA: DIAGNÓSTICO POR APRENDIZ
    // -------------------------------------------------------------
    function renderAprendicesTable(aprendices, isConsolidado = false) {
        const tbody = document.getElementById("tbody-aprendices");
        tbody.innerHTML = "";

        const searchTerm = document.getElementById("search-aprendiz").value.toLowerCase().trim();

        const filtered = aprendices.filter(a => {
            const matchesCategory = currentAprFilter === "all" || a.situacion_cod === currentAprFilter;
            const matchesSearch = !searchTerm ||
                a.nombre.toLowerCase().includes(searchTerm) ||
                a.documento.includes(searchTerm) ||
                (a.ficha && a.ficha.includes(searchTerm));
            return matchesCategory && matchesSearch;
        });

        if (filtered.length === 0) {
            tbody.innerHTML = `<tr><td colspan="10" style="text-align: center; color: var(--text-muted); padding: 2rem;">No se encontraron aprendices con ese criterio.</td></tr>`;
            return;
        }

        filtered.forEach(a => {
            const tr = document.createElement("tr");

            const fillClass = a.situacion_cod === "al_dia" ? "fill-green" : (a.situacion_cod === "observacion" ? "fill-amber" : "fill-red");
            const badgeClass = a.situacion_cod === "al_dia" ? "status-optimo" : (a.situacion_cod === "observacion" ? "status-avance" : "status-critico");

            tr.innerHTML = `
                <td style="font-weight: 600; color: var(--sena-primary);">${escapeHtml(a.ficha || '-')}</td>
                <td class="apr-name-col">${escapeHtml(a.nombre)}</td>
                <td>${escapeHtml(a.documento)}</td>
                <td><span style="font-size: 0.75rem; padding: 0.15rem 0.5rem; border-radius: 4px; background: rgba(255,255,255,0.06);">${escapeHtml(a.estado_sofia)}</span></td>
                <td style="color: var(--color-green); font-weight: 600;">${a.raps_aprobados}</td>
                <td style="color: ${a.raps_deficientes > 0 ? 'var(--color-red)' : 'var(--text-muted)'}; font-weight: 600;">${a.raps_deficientes}</td>
                <td style="color: var(--text-muted);">${a.raps_pendientes}</td>
                <td>
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <div class="kpi-progress-bar" style="width: 70px; margin-bottom: 0;">
                            <div class="progress-fill ${fillClass}" style="width: ${a.porcentaje_avance}%"></div>
                        </div>
                        <span style="font-weight: 600; font-size: 0.8rem;">${a.porcentaje_avance}%</span>
                    </div>
                </td>
                <td><span class="status-badge ${badgeClass}" style="display: inline-block;">${a.situacion}</span></td>
                <td>
                    <button class="btn-details" data-doc="${a.documento}">Ver Faltantes</button>
                </td>
            `;
            tbody.appendChild(tr);
        });

        // Eventos para abrir modal
        tbody.querySelectorAll(".btn-details").forEach(btn => {
            btn.addEventListener("click", () => {
                const doc = btn.dataset.doc;
                const currentData = activeFichaId === "ALL" 
                    ? multiAnalysisData.consolidado 
                    : multiAnalysisData.detalle_fichas[activeFichaId];
                const apr = currentData.aprendices.find(x => x.documento === doc);
                if (apr) openAprendizModal(apr);
            });
        });
    }

    document.getElementById("search-aprendiz").addEventListener("input", () => {
        if (multiAnalysisData) {
            const currentData = activeFichaId === "ALL" ? multiAnalysisData.consolidado : multiAnalysisData.detalle_fichas[activeFichaId];
            renderAprendicesTable(currentData.aprendices, activeFichaId === "ALL");
        }
    });

    document.querySelectorAll("#apr-status-filter .filter-chip").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll("#apr-status-filter .filter-chip").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentAprFilter = btn.dataset.filter;
            if (multiAnalysisData) {
                const currentData = activeFichaId === "ALL" ? multiAnalysisData.consolidado : multiAnalysisData.detalle_fichas[activeFichaId];
                renderAprendicesTable(currentData.aprendices, activeFichaId === "ALL");
            }
        });
    });

    // Modal de Aprendiz
    function openAprendizModal(apr) {
        modalAprName.textContent = apr.nombre;
        modalAprDoc.textContent = `Ficha: ${apr.ficha || '-'}  |  Documento: ${apr.documento}  |  Estado: ${apr.estado_sofia}  |  Avance: ${apr.porcentaje_avance}%`;

        let html = `
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; margin-bottom: 1.5rem; text-align: center;">
                <div style="background: rgba(16, 185, 129, 0.1); padding: 0.75rem; border-radius: 8px; border: 1px solid rgba(16, 185, 129, 0.3);">
                    <div style="font-size: 1.35rem; font-weight: 700; color: var(--color-green);">${apr.raps_aprobados}</div>
                    <div style="font-size: 0.75rem; color: var(--text-muted);">RAPs Aprobados</div>
                </div>
                <div style="background: rgba(239, 68, 68, 0.1); padding: 0.75rem; border-radius: 8px; border: 1px solid rgba(239, 68, 68, 0.3);">
                    <div style="font-size: 1.35rem; font-weight: 700; color: var(--color-red);">${apr.raps_deficientes}</div>
                    <div style="font-size: 0.75rem; color: var(--text-muted);">RAPs Deficientes</div>
                </div>
                <div style="background: rgba(245, 158, 11, 0.1); padding: 0.75rem; border-radius: 8px; border: 1px solid rgba(245, 158, 11, 0.3);">
                    <div style="font-size: 1.35rem; font-weight: 700; color: var(--color-amber);">${apr.raps_pendientes}</div>
                    <div style="font-size: 0.75rem; color: var(--text-muted);">RAPs por Evaluar</div>
                </div>
            </div>
        `;

        if (apr.raps_deficientes_lista && apr.raps_deficientes_lista.length > 0) {
            html += `
                <div class="modal-section-title" style="color: var(--color-red);">⚠️ RAPs Deficientes (Urgente Plan de Mejoramiento)</div>
                <ul class="modal-raps-list">
                    ${apr.raps_deficientes_lista.map(r => `<li><strong>${escapeHtml(r)}</strong></li>`).join("")}
                </ul>
            `;
        } else {
            html += `<div style="color: var(--color-green); font-size: 0.85rem; margin-bottom: 1rem;">✅ No presenta ningún RAP calificado como Deficiente (D).</div>`;
        }

        if (apr.raps_pendientes_lista && apr.raps_pendientes_lista.length > 0) {
            html += `
                <div class="modal-section-title" style="color: var(--color-amber); margin-top: 1.5rem;">⏳ RAPs Aún Pendientes de Evaluación</div>
                <ul class="modal-raps-list pending">
                    ${apr.raps_pendientes_lista.map(r => `<li>${escapeHtml(r)}</li>`).join("")}
                </ul>
            `;
        }

        modalAprContent.innerHTML = html;
        modalBackdrop.style.display = "flex";
    }

    btnCloseModal.addEventListener("click", () => modalBackdrop.style.display = "none");
    modalBackdrop.addEventListener("click", (e) => {
        if (e.target === modalBackdrop) modalBackdrop.style.display = "none";
    });

    // -------------------------------------------------------------
    // PESTAÑA: DESGLOSE POR COMPETENCIA
    // -------------------------------------------------------------
    function renderCompetenciasGrid(competencias) {
        const container = document.getElementById("competencias-container");
        container.innerHTML = "";

        if (!competencias || competencias.length === 0) {
            container.innerHTML = `<div style="text-align: center; color: var(--text-muted); padding: 2rem;">Selecciona una ficha específica para ver el desglose de competencias asociadas.</div>`;
            return;
        }

        competencias.forEach(c => {
            const card = document.createElement("div");
            card.className = "comp-card glass-panel";

            const fillClass = c.porcentaje_avance >= 80 ? "fill-green" : (c.porcentaje_avance >= 50 ? "fill-amber" : "fill-red");
            const statusClass = c.porcentaje_avance >= 80 ? "status-optimo" : (c.porcentaje_avance >= 50 ? "status-avance" : "status-critico");

            card.innerHTML = `
                <div>
                    <div class="comp-header">
                        <h4 class="comp-title">${escapeHtml(c.competencia)}</h4>
                        <span class="status-badge ${statusClass}">${c.estado}</span>
                    </div>
                </div>
                <div>
                    <div style="display: flex; justify-content: space-between; font-size: 0.85rem; font-weight: 600; margin-bottom: 0.4rem;">
                        <span>Avance Global</span>
                        <span>${c.porcentaje_avance}%</span>
                    </div>
                    <div class="kpi-progress-bar">
                        <div class="progress-fill ${fillClass}" style="width: ${c.porcentaje_avance}%"></div>
                    </div>
                </div>
                <div class="comp-stats-grid">
                    <div>
                        <div class="comp-stat-num">${c.total_raps}</div>
                        <div class="comp-stat-lbl">Total RAPs</div>
                    </div>
                    <div>
                        <div class="comp-stat-num" style="color: var(--color-green);">${c.aprobados}</div>
                        <div class="comp-stat-lbl">Aprobaciones</div>
                    </div>
                    <div>
                        <div class="comp-stat-num" style="color: ${c.deficientes > 0 ? 'var(--color-red)' : 'var(--text-muted)'};">${c.deficientes}</div>
                        <div class="comp-stat-lbl">Deficientes</div>
                    </div>
                </div>
            `;
            container.appendChild(card);
        });
    }

    // -------------------------------------------------------------
    // PESTAÑA: MATRIZ APRENDIZ X RAP
    // -------------------------------------------------------------
    function renderMatrix(matriz) {
        const thead = document.getElementById("thead-matrix");
        const tbody = document.getElementById("tbody-matrix");

        if (!matriz || !matriz.filas || matriz.filas.length === 0) {
            thead.innerHTML = "";
            tbody.innerHTML = `<tr><td style="text-align:center; padding: 2rem; color: var(--text-muted);">Selecciona una ficha específica en la barra superior para explorar la matriz cruzada de aprendices vs RAPs.</td></tr>`;
            return;
        }

        // Encabezados
        let headerHtml = `<tr><th>Documento</th><th>Nombre Aprendiz</th>`;
        matriz.raps.forEach((rap, idx) => {
            headerHtml += `<th title="${escapeHtml(rap)}">RAP ${idx + 1}</th>`;
        });
        headerHtml += `</tr>`;
        thead.innerHTML = headerHtml;

        // Filas
        let bodyHtml = "";
        matriz.filas.forEach(f => {
            bodyHtml += `<tr>`;
            bodyHtml += `<td>${escapeHtml(f.documento)}</td>`;
            bodyHtml += `<td class="apr-name-col">${escapeHtml(f.nombre)}</td>`;

            matriz.raps.forEach(rap => {
                const j = f.juicios[rap] || "P";
                const badgeClass = j === "A" ? "badge-a" : (j === "D" ? "badge-d" : "badge-p");
                bodyHtml += `<td><span class="${badgeClass}" title="${escapeHtml(rap)}: ${j}">${j}</span></td>`;
            });
            bodyHtml += `</tr>`;
        });
        tbody.innerHTML = bodyHtml;
    }

    // -------------------------------------------------------------
    // CONTROL DE PESTAÑAS (TABS)
    // -------------------------------------------------------------
    document.querySelectorAll(".tab-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
            document.querySelectorAll(".tab-content").forEach(tc => tc.classList.remove("active"));

            btn.classList.add("active");
            const tabId = btn.dataset.tab;
            const targetContent = document.getElementById(tabId);
            if (targetContent) targetContent.classList.add("active");
        });
    });

    // -------------------------------------------------------------
    // EXPORTACIÓN A EXCEL
    // -------------------------------------------------------------
    btnExportExcel.addEventListener("click", () => {
        window.location.href = "/api/export";
        showToast("Generando y descargando informe oficial consolidado en Excel...");
    });

    // -------------------------------------------------------------
    // FILTROS DE ESTADO Y UMBRALES
    // -------------------------------------------------------------
    function setupStateChips(states) {
        stateChipsContainer.innerHTML = "";
        selectedStates.clear();

        if (!states || states.length === 0) {
            controlsBar.style.display = "none";
            return;
        }

        controlsBar.style.display = "flex";

        states.forEach(st => {
            const chip = document.createElement("button");
            chip.type = "button";
            chip.className = "state-chip";
            chip.textContent = st;

            if (st.includes("FORMACI") || states.length === 1) {
                chip.classList.add("active");
                selectedStates.add(st);
            }

            chip.addEventListener("click", () => {
                if (selectedStates.has(st)) {
                    if (selectedStates.size > 1) {
                        selectedStates.delete(st);
                        chip.classList.remove("active");
                    } else {
                        showToast("Debe mantener al menos un estado seleccionado", true);
                    }
                } else {
                    selectedStates.add(st);
                    chip.classList.add("active");
                }
            });

            stateChipsContainer.appendChild(chip);
        });
    }

    btnApplyFilters.addEventListener("click", async () => {
        if (!multiAnalysisData) return;
        showToast("Recalculando avance de todas las fichas...");

        const filter_estados = Array.from(selectedStates);
        const umbral_verde = parseFloat(inputUmbralVerde.value) || 80.0;
        const umbral_amarillo = parseFloat(inputUmbralAmarillo.value) || 50.0;

        try {
            const res = await fetch("/api/analyze", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    filter_estados,
                    umbral_verde,
                    umbral_amarillo
                })
            });

            const data = await res.json();
            if (!data.success) {
                throw new Error(data.error);
            }

            setMultiAnalysisData(data.analysis);
            showToast("Métricas y semáforos recalculados exitosamente");
        } catch (err) {
            showToast(err.message, true);
        }
    });

    function escapeHtml(text) {
        if (!text) return "";
        return text.toString()
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    // Cargar automáticamente el conjunto de fichas de prueba al iniciar
    loadSampleData(false);
});
