import streamlit as st
import os
import json
import time
from google.cloud import storage

# --- CONFIGURAZIONE CORE ---
BUCKET_NAME = "cad-vault-marco"

st.set_page_config(page_title="PORTALE CAD", layout="wide", page_icon="🏗️")

# --- FUNZIONE DI SICUREZZA ---
def check_password():
    """Restituisce True se l'utente ha inserito la password corretta tramite Secrets."""
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if not st.session_state["password_correct"]:
        st.title("🔒 Accesso Riservato")
        pwd = st.text_input("Inserisci la password dell'Archivio", type="password")
        if st.button("Accedi"):
            try:
                if pwd == st.secrets["login"]["password"]:
                    st.session_state["password_correct"] = True
                    st.rerun()
                else:
                    st.error("Password errata")
            except KeyError:
                st.error("Errore di configurazione: 'login/password' non trovato nei Secrets.")
        return False
    return True

# --- LOGICA ESECUZIONE ---
if check_password():
    # 1. IMMAGINE DI COPERTINA
    try:
        st.image("cover.jpg", use_container_width=True)
    except:
        st.info("Immagine di copertina non caricata.")

    # 2. NUOVO CSS "CHROME STYLE"
    st.markdown("""
        <style>
        /* Sfondo generale chiaro stile Chrome */
        .stApp { background-color: #f8f9fa; }
        
        /* Personalizzazione TAB stile Chrome */
        .stTabs [data-baseweb="tab-list"] {
            gap: 2px;
            background-color: #dee2e6;
            padding: 5px 5px 0px 5px;
            border-radius: 5px 5px 0 0;
        }
        .stTabs [data-baseweb="tab"] {
            background-color: #e9ecef;
            border: none;
            padding: 10px 20px;
            color: #495057 !important;
            font-weight: 500 !important;
            border-radius: 5px 5px 0 0;
            transition: all 0.2s;
        }
        .stTabs [data-baseweb="tab"]:hover {
            background-color: #f8f9fa;
        }
        .stTabs [aria-selected="true"] {
            background-color: #ffffff !important;
            color: #1a73e8 !important; /* Blu Chrome */
            border-bottom: 3px solid #1a73e8 !important;
        }
        
        /* Box e Input */
        .stTextInput>div>div>input, .stTextArea>div>div>textarea, .stSelectbox>div>div>div {
            border: 1px solid #ced4da !important;
            border-radius: 4px !important;
            background-color: #ffffff !important;
        }
        
        /* Pulsanti Premium */
        .stButton>button {
            background-color: #1a73e8;
            color: white !important;
            border-radius: 4px;
            border: none;
            font-weight: 500;
            height: 45px;
            width: 100%;
        }
        .stButton>button:hover {
            background-color: #1557b0;
            color: white !important;
        }

        /* Testi e Labels */
        label, p, h1, h2, h3, h4 { color: #212529 !important; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        </style>
        """, unsafe_allow_html=True)

    # Inizializzazione Google Cloud dai Secrets
    try:
        gcp_info = json.loads(st.secrets["gcp_service_account"])
        client = storage.Client.from_service_account_info(gcp_info)
        bucket = client.bucket(BUCKET_NAME)
    except Exception as e:
        st.error(f"Errore di connessione a Google Cloud: {e}")
        st.stop()

    # RECUPERO CATEGORIE DINAMICHE
    try:
        cats_json = bucket.blob("metadata/categories.json").download_as_text()
        lista_categorie = json.loads(cats_json)
    except:
        lista_categorie = ["Aggiornamento categorie in corso..."]

    tab1, tab2 = st.tabs(["📤 CHECK-IN", "🔍 CHECK-OUT"])

    # --- TAB 1: CHECK-IN ---
    with tab1:
        st.subheader("Nuovo Articolo nell'Archivio")
        st.info("Carica i file 3D e 2D per un singolo codice articolo.")
        
        with st.form("form_checkin", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                nome_articolo = st.text_input("Codice Articolo", placeholder="es. PRJ-001")
                categoria = st.selectbox("Categoria", lista_categorie)
            with col2:
                tags = st.text_input("Tag (es. alluminio, lavorato)")
                solo_trasferimento = st.checkbox("Solo Trasferimento (Nessuna elaborazione)")

            note = st.text_area("Note Tecniche")
            upload_files = st.file_uploader("Documentazione CAD", accept_multiple_files=True)
            
            if st.form_submit_button("INVIA CODICE"):
                if upload_files and nome_articolo:
                    with st.spinner("Sincronizzazione in corso..."):
                        task_data = {
                            "nome_articolo": nome_articolo,
                            "categoria": categoria,
                            "tags": [t.strip() for t in tags.split(",")] if tags else [],
                            "note": note,
                            "solo_trasferimento": solo_trasferimento,
                            "timestamp": time.time()
                        }
                        bucket.blob(f"inbox/{nome_articolo}.json").upload_from_string(json.dumps(task_data, indent=4))
                        for f in upload_files:
                            bucket.blob(f"inbox/{nome_articolo}/{f.name}").upload_from_file(f)
                        st.balloons()
                        st.success(f"Archiviazione per {nome_articolo} avviata con successo.")
                else:
                    st.error("Inserire codice e file.")

    # --- TAB 2: CHECK-OUT ---
    with tab2:
        st.subheader("Ricerca Articoli")
        
        # Lettura archivio.json dal Cloud
        try:
            idx_blob = bucket.blob("metadata/archivio_index.json").download_as_text()
            index_data = json.loads(idx_blob)["components"]
        except:
            st.error("Indice Centrale non disponibile via Cloud.")
            index_data = []

        # GRIGLIA DI RICERCA
        c1, c2 = st.columns(2)
        with c1: n1 = st.text_input("Parola 1").lower()
        with c2: n2 = st.text_input("Parola 2").lower()
        
        t1, t2, t3 = st.columns(3)
        with t1: tag1 = st.text_input("Tag 1").lower()
        with t2: tag2 = st.text_input("Tag 2").lower()
        with t3: tag3 = st.text_input("Tag 3").lower()

        if index_data:
            results = []
            for item in index_data:
                code = item.get('code', '').lower()
                tags_list = " ".join(item.get('tags', [])).lower()
                if (n1 in code and n2 in code) and (tag1 in tags_list and tag2 in tags_list and tag3 in tags_list):
                    results.append(item)

            st.write(f"**Risultati filtrati ({len(results)}):**")
            
            # IL CONTENITORE SCORREVOLE (UX Scalabile per Chrome Style)
            selected_codes = []
            with st.container(height=450):
                for res in results:
                    if st.checkbox(f"📦 {res['code']} | {res['category']}", key=f"out_{res['code']}"):
                        selected_codes.append(res['code'])
            
            st.write("---")
            if st.button("PREPARA LINK DI DOWNLOAD"):
                if selected_codes:
                    req_id = int(time.time())
                    req = {"items": selected_codes, "request_id": req_id, "timestamp": time.time()}
                    bucket.blob(f"requests/req_{req_id}.json").upload_from_string(json.dumps(req, indent=4))
                    st.session_state['last_req_id'] = req_id
                    st.success(f"Richiesta prelievo {req_id} inviata.")
                else:
                    st.error("Selezionare almeno un articolo.")
            
            if 'last_req_id' in st.session_state:
                req_id = st.session_state['last_req_id']
                res_blob = bucket.blob(f"responses/{req_id}.json")
                if res_blob.exists():
                    res_data = json.loads(res_blob.download_as_text())
                    st.link_button("🚀 SCARICA ZIP PRONTO", res_data['url'])
                else:
                    if st.button("🔄 AGGIORNA STATO"):
                        st.rerun()
