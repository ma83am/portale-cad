import streamlit as st
import os
import json
import time
from google.cloud import storage

# --- CONFIGURAZIONE ---
BUCKET_NAME = "cad-vault-marco"
st.set_page_config(page_title="PORTALE CAD", layout="wide", page_icon="🏗️")

# --- LOGICA DI STATO ---
if "limit_results" not in st.session_state:
    st.session_state.limit_results = 25
if "download_queue" not in st.session_state:
    st.session_state.download_queue = set()
if "f1_query" not in st.session_state:
    st.session_state.f1_query = ""
if "password_correct" not in st.session_state:
    st.session_state["password_correct"] = False

def show_more():
    st.session_state.limit_results += 25

def check_password():
    if not st.session_state["password_correct"]:
        st.title("🔒 Accesso Riservato")
        pwd = st.text_input("Inserisci la password", type="password")
        if st.button("Accedi"):
            if pwd == st.secrets["login"]["password"]:
                st.session_state["password_correct"] = True
                st.rerun()
            else: st.error("Password errata")
        return False
    return True

def get_sync_data(bucket):
    try:
        q_blob = bucket.blob("metadata/sync_queue.json")
        h_blob = bucket.blob("metadata/history.json")
        queue = json.loads(q_blob.download_as_text()) if q_blob.exists() else {}
        history = json.loads(h_blob.download_as_text()) if h_blob.exists() else []
        return queue, history
    except: return {}, []

@st.dialog("Anteprima Tecnica Articolo", width="large")
def preview_dialog(item, bucket):
    st.write(f"🔍 **Dettaglio Codice:** {item['code']}")
    img_formats = [f for f in item.get('formats', []) if f.upper() in ['JPG', 'PNG', 'JPEG']]
    if img_formats:
        ext = img_formats[0].lower()
        cloud_path = f"archive/{item['code']}/{item['code']}.{ext}"
        try:
            blob = bucket.blob(cloud_path)
            img_bytes = blob.download_as_bytes()
            st.image(img_bytes) 
            st.download_button("💾 Scarica questa immagine", img_bytes, file_name=f"{item['code']}.jpg")
        except:
            st.error("L'immagine non è ancora disponibile nel Cloud.")
            if st.button("🚀 Richiedi Sincronizzazione Urgente"):
                q, h = get_sync_data(bucket)
                q[item['code']] = {"synced": False, "formats": img_formats, "timestamp": time.time()}
                bucket.blob("metadata/sync_queue.json").upload_from_string(json.dumps(q))
                st.success("Richiesta inviata!")
    else: st.warning("Nessuna anteprima disponibile.")
    st.divider()
    st.json({"Tag": item.get('tags', []), "Formati": item.get('formats', [])})

# --- LOGICA PRINCIPALE ---
if check_password():
    gcp_info = json.loads(st.secrets["gcp_service_account"])
    client = storage.Client.from_service_account_info(gcp_info)
    bucket = client.bucket(BUCKET_NAME)

    # --- SIDEBAR: DASHBOARD ---
    queue, history = get_sync_data(bucket)
    with st.sidebar:
        st.subheader("📡 Stato Sistema")
        try:
            hb = json.loads(bucket.blob("metadata/heartbeat.json").download_as_text())
            if (time.time() - hb['last_seen']) < 120:
                st.success("🟢 PC ARCHIVIO ONLINE")
            else: st.error("🔴 PC ARCHIVIO OFFLINE")
        except: st.warning("⚪ STATO NON DISPONIBILE")
        
        st.divider()
        st.subheader("⏳ Coda Sync / 🕒 Recenti")
        pending = {k: v for k, v in queue.items() if not v.get('synced', False)}
        if pending:
            for code in pending: st.info(f"**{code}**\nSincronizzazione...")
        
        ready = {k: v for k, v in queue.items() if v.get('synced', False)}
        for code in list(ready.keys()):
            if st.button(f"✅ {code} PRONTO", key=f"ready_{code}"):
                if code not in history:
                    history.insert(0, code)
                    bucket.blob("metadata/history.json").upload_from_string(json.dumps(history[:20]))
                del queue[code]
                bucket.blob("metadata/sync_queue.json").upload_from_string(json.dumps(queue))
                st.rerun()

        st.divider()
        if history:
            for old_code in history:
                if st.button(f"📄 {old_code}", key=f"hist_{old_code}", use_container_width=True):
                    st.session_state.f1_query = old_code
                    st.rerun()

    # --- INTESTAZIONE ---
    st.image("cover.jpg", use_container_width=True)
    st.title("🏗️ Portale CAD Centrale")

    # CSS "CHROME STYLE"
    st.markdown("""
        <style>
        .stApp { background-color: #f8f9fa; }
        .stTabs [data-baseweb="tab-list"] { gap: 2px; background-color: #dee2e6; padding: 5px 5px 0px 5px; border-radius: 5px 5px 0 0; }
        .stTabs [data-baseweb="tab"] { background-color: #e9ecef; border: none; padding: 10px 20px; color: #495057 !important; font-weight: 500 !important; border-radius: 5px 5px 0 0; }
        .stTabs [aria-selected="true"] { background-color: #ffffff !important; color: #1a73e8 !important; border-bottom: 3px solid #1a73e8 !important; }
        .stButton>button { background-color: #1a73e8; color: white !important; border-radius: 4px; border: none; font-weight: 500; height: 40px; }
        label, p, h1, h2, h3 { color: #212529 !important; font-family: 'Segoe UI', sans-serif; }
        </style>
        """, unsafe_allow_html=True)

    # --- CARICAMENTO MAPPA CATEGORIE (BLINDATO) ---
    try:
        cat_blob = bucket.blob("metadata/categories.json")
        raw_cats = json.loads(cat_blob.download_as_text())
        
        # Se è una lista (vecchio formato), la convertiamo al volo in dizionario
        if isinstance(raw_cats, list):
            cat_map = {c: [] for c in raw_cats}
        else:
            cat_map = raw_cats
    except Exception:
        # Se il file non esiste ancora o c'è un errore, usiamo un fallback sicuro
        cat_map = {
            "1_ASSIEMI": [], 
            "2_GRUPPI": [], 
            "3_COMPONENTI A DISEGNO": [],
            "4_COMMERCIALI": ["A CATALOGO", "COMMERCIALI_LAVORATI", "GENERICI"],
            "9_NON CLASSIFICATI": []
        }

    tab1, tab2 = st.tabs(["📤 CHECK-IN (Inserimento)", "🔍 CHECK-OUT (Ricerca)"])

    # --- TAB 1: CHECK-IN ---
    with tab1:
        st.subheader("Archiviazione Nuovo Articolo")
        with st.form("form_checkin", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1: nome = st.text_input("Codice Articolo (es. GUIDA_PALLET_L1500)")
            with c2: tags = st.text_input("Tag (es. saldato, rulliera, AISI304)")

            # BOX 1: Selezione cartella principale
            main_categories = list(cat_map.keys())
            main_cat = st.selectbox("Seleziona Cartella Principale", main_categories)
            
            # BOX 2: Selezione sottocartella (appare solo se esistono sub-folders)
            subs = cat_map.get(main_cat, [])
            full_cat = main_cat
            if subs:
                sub_cat = st.selectbox("Seleziona Sottocartella", subs)
                full_cat = f"{main_cat}/{sub_cat}"
            
            st.info(f"📍 Destinazione: D:/ARCHIVIO CAD/{full_cat}/{nome}")
            
            solo_tra = st.checkbox("Solo trasferimento (inbox)")
            files = st.file_uploader("Trascina i file dell'articolo", accept_multiple_files=True)
            
            if st.form_submit_button("ESEGUI CHECK-IN"):
                if files and nome:
                    with st.spinner("Invio..."):
                        task_data = {"nome_articolo": nome, "categoria": full_cat, "tags": tags, "solo_trasferimento": solo_tra, "timestamp": time.time()}
                        bucket.blob(f"inbox/{nome}.json").upload_from_string(json.dumps(task_data, indent=4))
                        for f in files:
                            bucket.blob(f"inbox/{nome}/{f.name}").upload_from_file(f)
                        st.success("Richiesta inviata.")
                else: st.error("Dati incompleti.")

    # --- TAB 2: CHECK-OUT ---
    with tab2:
        st.subheader("Ricerca e Prelievo")
        try:
            idx_blob = bucket.blob("metadata/archivio_index.json").download_as_text()
            index_data = json.loads(idx_blob)["components"]
        except: st.error("Indice non disponibile."); index_data = []

        c1, c2 = st.columns(2)
        with c1: 
            n1 = st.text_input("Ricerca Nome 1", value=st.session_state.f1_query, key="f1").lower()
            st.session_state.f1_query = ""
        with c2: n2 = st.text_input("Ricerca Nome 2", key="f2").lower()
        t1, t2, t3 = st.columns(3)
        with t1: tag1 = t1.text_input("Tag 1", key="f3").lower()
        with t2: tag2 = t2.text_input("Tag 2", key="f4").lower()
        with t3: tag3 = t3.text_input("Tag 3", key="f5").lower()

        filtered = [item for item in index_data if (n1 in (item.get('code', '') + " " + " ".join(item.get('tags', []))).lower() and n2 in (item.get('code', '') + " " + " ".join(item.get('tags', []))).lower()) and (tag1 in (item.get('code', '') + " " + " ".join(item.get('tags', []))).lower() and tag2 in (item.get('code', '') + " " + " ".join(item.get('tags', []))).lower() and tag3 in (item.get('code', '') + " " + " ".join(item.get('tags', []))).lower())]
        st.info(f"📍 Risultati: {len(filtered)} | Coda: {len(st.session_state.download_queue)}")

        with st.container(height=500, border=True):
            for item in filtered[:st.session_state.limit_results]:
                col_info, col_btn_pre, col_btn_sel = st.columns([4, 1, 1])
                with col_info:
                    st.write(f"📦 **{item['code']}**")
                    st.caption(f"{item['category']} | Tags: {', '.join(item['tags'][:3])}...")
                with col_btn_pre:
                    if st.button("👁️ Anteprima", key=f"pre_{item['code']}"): preview_dialog(item, bucket)
                with col_btn_sel:
                    is_selected = item['code'] in st.session_state.download_queue
                    if st.button("✅" if is_selected else "📥", key=f"sel_{item['code']}", type="secondary" if is_selected else "primary"):
                        if is_selected: st.session_state.download_queue.remove(item['code'])
                        else: st.session_state.download_queue.add(item['code'])
                        st.rerun()

        if len(filtered) > st.session_state.limit_results:
            st.button("Mostra altri risultati...", on_click=show_more)

        st.write("---")
        if st.button("🚀 GENERA LINK PER DOWNLOAD (ZIP)"):
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
                st.link_button("🔥 SCARICA ZIP", res_data['url'], use_container_width=True)
                if st.button("Svuota coda"): st.session_state.download_queue.clear(); st.rerun()
            else:
                if st.button("🔄 AGGIORNA"): st.rerun()
