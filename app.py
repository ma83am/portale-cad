import streamlit as st
import json
import time
import os
from google.cloud import storage

# --- 1. DEFINIZIONE RIGIDA CATEGORIE ---
CATEGORIE_FISSE = {
    "1_ASSIEMI": "1_ASSIEMI",
    "2_GRUPPI": "2_GRUPPI",
    "3_COMPONENTI A DISEGNO": "3_COMPONENTI A DISEGNO",
    "4_COMMERCIALI": "4_COMMERCIALI",
    "4.1_A CATALOGO": "4_COMMERCIALI/4.1_A CATALOGO",
    "4.2_COMMERCIALI_LAVORATI": "4_COMMERCIALI/4.2_COMMERCIALI_LAVORATI",
    "4.3_GENERICI": "4_COMMERCIALI/4.3_GENERICI",
    "8_CATALOGHI": "8_CATALOGHI",
    "9_NON CLASSIFICATI": "9_NON CLASSIFICATI"
}

# --- CONFIGURAZIONE CORE ---
BUCKET_NAME = "cad-vault-marco"
st.set_page_config(page_title="Vault CAD Marco", layout="wide", page_icon="🏗️")

# --- CSS REFINEMENT (Version 4.2) ---
st.markdown("""
    <style>
    /* Icone minimali per i bottoni in colonna */
    div[data-testid="column"] button { 
        border: none !important; 
        background-color: transparent !important; 
        font-size: 24px !important; 
        padding: 0px !important; 
        transition: transform 0.2s, color 0.2s;
        box-shadow: none !important;
    }
    div[data-testid="column"] button:hover { 
        transform: scale(1.3); 
        color: #0078D4 !important; 
    }
    div[data-testid="column"] button:active {
        color: #28a745 !important;
    }
    /* Pulsanti Sidebar */
    .stButton > button { width: 100%; border-radius: 5px; }
    /* Logout button specifico */
    .logout-btn { color: #d9534f !important; font-size: 14px !important; text-align: left !important; }
    
    .stDownloadButton button { 
        border: 1px solid #ddd !important; 
        background-color: #f9f9f9 !important; 
        font-size: 14px !important; 
        padding: 5px 15px !important; 
        border-radius: 5px !important;
    }
    .stCheckbox { margin-top: 10px; }
    .stAlert { border-radius: 10px; }
    label, p, h1, h2, h3 { color: #212529 !important; font-family: 'Segoe UI', sans-serif; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. GESTIONE SESSIONE (F5 PERSISTENCE & 2H TIMER) ---
def check_password():
    # Recupera parametri dall'URL per sopravvivere a F5
    params = st.query_params
    if params.get("auth") == "true":
        try:
            login_time = float(params.get("t", 0))
            # Verifica timer 2 ore (7200 secondi)
            if (time.time() - login_time) < 7200:
                return True
            else:
                st.query_params.clear()
                st.warning("Sessione scaduta dopo 2 ore. Effettua di nuovo l'accesso.")
        except:
            st.query_params.clear()

    # Schermata di Login
    st.title("🔒 Accesso Riservato Vault")
    pwd = st.text_input("Password di sistema", type="password")
    if st.button("Accedi"):
        if pwd == st.secrets["login"]["password"]:
            st.query_params["auth"] = "true"
            st.query_params["t"] = str(time.time())
            st.rerun()
        else:
            st.error("Password errata.")
    return False

def logout():
    st.query_params.clear()
    st.rerun()

# --- LOGICA DI STATO ---
if "limit_results" not in st.session_state:
    st.session_state.limit_results = 25
if "download_queue" not in st.session_state: 
    st.session_state.download_queue = set()
if "f1_query" not in st.session_state:
    st.session_state.f1_query = ""

def show_more():
    st.session_state.limit_results += 25

# --- ESECUZIONE ---
if check_password():
    # Connessione Cloud
    gcp_info = json.loads(st.secrets["gcp_service_account"])
    client = storage.Client.from_service_account_info(gcp_info)
    bucket = client.bucket(BUCKET_NAME)

    # Helper JSON
    def get_cloud_json(path):
        try:
            blob = bucket.blob(path)
            return json.loads(blob.download_as_text()) if blob.exists() else {}
        except: return {}

    def save_cloud_json(path, data):
        bucket.blob(path).upload_from_string(json.dumps(data))

    def add_to_sync(code, fmts):
        fmt_list = [fmts] if isinstance(fmts, str) else fmts
        queue = get_cloud_json("metadata/sync_queue.json")
        if code not in queue: queue[code] = {"formats": [], "synced": False}
        for f in fmt_list:
            if f not in queue[code]["formats"]: queue[code]["formats"].append(f)
        save_cloud_json("metadata/sync_queue.json", queue)
        st.toast(f"Richiesta inviata al PC per {code}")

    # --- 3. SIDEBAR ---
    with st.sidebar:
        st.title("⚙️ Sistema Vault")
        
        # Stato Server
        hb = get_cloud_json("metadata/heartbeat.json")
        if (time.time() - hb.get('last_seen', 0)) < 120:
            st.success("● ARCHIVIO ONLINE")
        else:
            st.error("● ARCHIVIO OFFLINE")
            
        # LOGOUT (Sotto lo stato)
        if st.button("🚪 Esci dal sistema", help="Chiudi la sessione e disconnetti"):
            logout()
            
        st.divider()
        st.subheader("⏳ In Sincronizzazione")
        queue = get_cloud_json("metadata/sync_queue.json")
        if not queue: st.caption("Coda vuota.")
        for code in queue: st.write(f"⏳ {code}...")

        st.divider()
        st.subheader("🕒 Recenti (Scadenza 24h)")
        history = get_cloud_json("metadata/history.json")
        if not history: st.caption("Nessuna cronologia.")
        else:
            for entry in list(history)[:10]:
                elapsed = time.time() - entry['timestamp_sync']
                rem = 24 - int(elapsed / 3600)
                if rem > 0:
                    with st.expander(f"📦 {entry['code']} ({rem}h rimaste)"):
                        for f in entry.get('formats', []):
                            b = bucket.blob(f"archive/{entry['code']}/{entry['code']}.{f.lower()}")
                            if b.exists():
                                st.download_button(f"Scarica {f}", b.download_as_bytes(), 
                                                 f"{entry['code']}.{f.lower()}", key=f"hdl_{entry['code']}_{f}")
                            else: st.caption(f"⏳ {f}")
                else: st.caption(f"📦 {entry['code']} (Scaduto)")

    # --- 4. CORPO CENTRALE ---
    st.image("cover.jpg", use_container_width=True)
    st.title("🏗️ Vault CAD Centrale")
    t1, t2 = st.tabs(["📤 CHECK-IN", "🔍 CHECK-OUT"])

    # --- DIALOG ANTEPRIMA ---
    @st.dialog("Dettaglio Tecnico Articolo", width="large")
    def preview_dialog(item):
        st.subheader(f"📦 {item['code']}")
        img_f = [f for f in item['formats'] if f.upper() in ['PNG', 'JPG', 'JPEG']]
        if img_f:
            img_blob = bucket.blob(f"archive/{item['code']}/{item['code']}.{img_f[0].lower()}")
            if img_blob.exists(): st.image(img_blob.download_as_bytes())
            else: st.info("📸 Immagine in fase di sincronizzazione...")
        st.divider()
        col_tags, col_files = st.columns([1, 1])
        with col_tags:
            st.write("**🏷️ Tag Associati:**")
            st.write(", ".join(item.get('tags', [])) if item.get('tags') else "Nessuno")
        with col_files:
            st.write("**📂 Formati (Download Singoli):**")
            q = get_cloud_json("metadata/sync_queue.json")
            for fmt in item['formats']:
                ext = fmt.lower()
                blob = bucket.blob(f"archive/{item['code']}/{item['code']}.{ext}")
                c_btn, c_stat = st.columns([1, 4])
                with c_btn:
                    if blob.exists():
                        st.download_button(label=f"⬇️ {fmt}", data=blob.download_as_bytes(), 
                                         file_name=f"{item['code']}.{ext}", key=f"dl_{item['code']}_{fmt}")
                    elif item['code'] in q and fmt in q[item['code']]['formats']:
                        st.button(f"⏳ {fmt}", key=f"wait_{item['code']}_{fmt}", disabled=True)
                    else:
                        if st.button(f"⏳ {fmt}", key=f"req_{item['code']}_{fmt}"):
                            add_to_sync(item['code'], fmt)
                            st.rerun()

    # TAB 1: CHECK-IN
    with t1:
        st.subheader("Nuovo Inserimento")
        col1, col2 = st.columns(2)
        with col1: nome_art = st.text_input("Codice Articolo", placeholder="es. GUIDA_PALLET")
        with col2: tags_art = st.text_input("Tag (separati da virgola)")
        sel_cat = st.selectbox("Seleziona Categoria", list(CATEGORIE_FISSE.keys()))
        path_rel = CATEGORIE_FISSE[sel_cat]
        st.info(f"📍 Destinazione: D:/ARCHIVIO CAD/{path_rel}/{nome_art if nome_art else '...'}/")
        files = st.file_uploader("Trascina i file dell'articolo", accept_multiple_files=True)
        if st.button("🚀 ESEGUI CHECK-IN", use_container_width=True, type="primary"):
            if nome_art and files:
                with st.spinner("Invio al Cloud..."):
                    task = {"nome_articolo": nome_art, "percorso_relativo": path_rel, "tags": [t.strip() for t in tags_art.split(',')], "solo_trasferimento": False}
                    prefix = f"inbox/{nome_art}_{int(time.time())}"
                    bucket.blob(f"{prefix}/{nome_art}_task.json").upload_from_string(json.dumps(task))
                    for f in files:
                        bucket.blob(f"{prefix}/{f.name}").upload_from_string(f.getvalue())
                    st.success("Richiesta inviata al Bridge locale!")
            else: st.error("Codice e File sono obbligatori.")

    # TAB 2: CHECK-OUT
    with t2:
        st.subheader("Ricerca nell'Archivio")
        idx_data = get_cloud_json("metadata/archivio_index.json").get("components", [])
        
        # Filtri Avanzati (Multi-Tag)
        c1, c2 = st.columns(2)
        with c1: 
            n1 = st.text_input("Codice Parte 1", value=st.session_state.f1_query, key="f1").lower()
            st.session_state.f1_query = ""
        with c2: n2 = st.text_input("Codice Parte 2", key="f2").lower()
        t1, t2, t3 = st.columns(3)
        with t1: tag1 = t1.text_input("Tag 1", key="t1").lower()
        with t2: tag2 = t2.text_input("Tag 2", key="t2").lower()
        with t3: tag3 = t3.text_input("Tag 3", key="t3").lower()

        filtered = [i for i in idx_data if 
                    (n1 in i['code'].lower() and n2 in i['code'].lower()) and
                    (tag1 in " ".join(i.get('tags', [])).lower() and tag2 in " ".join(i.get('tags', [])).lower() and tag3 in " ".join(i.get('tags', [])).lower())]
        
        st.info(f"📍 Risultati: {len(filtered)} | Coda ZIP: {len(st.session_state.download_queue)}")

        with st.container(height=550, border=False):
            for item in filtered[:st.session_state.limit_results]:
                with st.container(border=True):
                    c_txt, c_view, c_plus = st.columns([0.8, 0.1, 0.1])
                    with c_txt:
                        st.markdown(f"**{item['code']}**")
                        st.caption(f"{item['category']} | Formati: {', '.join(item['formats'])}")
                    with c_view:
                        if st.button("🔍", key=f"v_{item['code']}"): preview_dialog(item)
                    with c_plus:
                        is_sel = item['code'] in st.session_state.download_queue
                        if st.button("✅" if is_sel else "➕", key=f"a_{item['code']}"):
                            if is_sel: st.session_state.download_queue.remove(item['code'])
                            else: 
                                st.session_state.download_queue.add(item['code'])
                                add_to_sync(item['code'], item['formats'])
                            st.rerun()

        if len(filtered) > st.session_state.limit_results:
            st.button("Mostra altri risultati...", on_click=show_more)

        st.write("---")
        if st.button("🚀 GENERA LINK PER DOWNLOAD (ZIP)", type="primary", use_container_width=True):
            if st.session_state.download_queue:
                req_id = int(time.time())
                bucket.blob(f"requests/req_{req_id}.json").upload_from_string(json.dumps({"items": list(st.session_state.download_queue), "request_id": req_id, "timestamp": time.time()}, indent=4))
                st.session_state['last_req_id'] = req_id
                st.success(f"Richiesta {req_id} inviata.")
            else: st.error("Coda vuota.")
        
        if 'last_req_id' in st.session_state:
            res_blob = bucket.blob(f"responses/{st.session_state['last_req_id']}.json")
            if res_blob.exists():
                res_data = json.loads(res_blob.download_as_text())
                st.link_button("🔥 SCARICA ZIP PRONTO", res_data['url'], use_container_width=True)
                if st.button("Svuota coda"): st.session_state.download_queue.clear(); st.rerun()
            else:
                if st.button("🔄 AGGIORNA STATO PRELIEVO"): st.rerun()
