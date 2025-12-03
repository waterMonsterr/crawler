import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
import sqlite3
import pydeck as pdk

# --- 設定頁面 ---
st.set_page_config(
    page_title="一週農業氣象預報 (SQLite版)",
    page_icon="🌤️",
    layout="wide"
)

# --- 資料庫設定 ---
DB_NAME = "data.db"

# --- [新功能] 擴充地點映射表 ---
# 雖然 API 只給 "北部地區"，但我們將其映射到該區的所有縣市，讓地圖更豐富
CITY_MAPPING = [
    {"city": "基隆市", "region": "北部地區", "lat": 25.1276, "lon": 121.7392},
    {"city": "臺北市", "region": "北部地區", "lat": 25.0330, "lon": 121.5654},
    {"city": "新北市", "region": "北部地區", "lat": 25.0172, "lon": 121.4625},
    {"city": "桃園市", "region": "北部地區", "lat": 24.9936, "lon": 121.3010},
    {"city": "新竹市", "region": "北部地區", "lat": 24.8138, "lon": 120.9675},
    {"city": "新竹縣", "region": "北部地區", "lat": 24.8396, "lon": 121.0107},
    {"city": "苗栗縣", "region": "北部地區", "lat": 24.5602, "lon": 120.8214},
    
    {"city": "臺中市", "region": "中部地區", "lat": 24.1477, "lon": 120.6736},
    {"city": "彰化縣", "region": "中部地區", "lat": 24.0518, "lon": 120.5161},
    {"city": "南投縣", "region": "中部地區", "lat": 23.9610, "lon": 120.9719},
    {"city": "雲林縣", "region": "中部地區", "lat": 23.7092, "lon": 120.4313},
    {"city": "嘉義市", "region": "中部地區", "lat": 23.4801, "lon": 120.4491},
    {"city": "嘉義縣", "region": "中部地區", "lat": 23.4518, "lon": 120.2555},
    
    {"city": "臺南市", "region": "南部地區", "lat": 22.9997, "lon": 120.2270},
    {"city": "高雄市", "region": "南部地區", "lat": 22.6273, "lon": 120.3014},
    {"city": "屏東縣", "region": "南部地區", "lat": 22.5519, "lon": 120.5487},
    
    {"city": "宜蘭縣", "region": "東北部地區", "lat": 24.7021, "lon": 121.7377},
    {"city": "花蓮縣", "region": "東部地區", "lat": 23.9872, "lon": 121.6011},
    {"city": "臺東縣", "region": "東南部地區", "lat": 22.7613, "lon": 121.1445},
    
    # 離島部分若 API 有提供對應區域才顯示，若無則會自動過濾
    {"city": "澎湖縣", "region": "澎湖地區", "lat": 23.5711, "lon": 119.5793},
    {"city": "金門縣", "region": "金門地區", "lat": 24.4404, "lon": 118.3225},
    {"city": "連江縣", "region": "馬祖地區", "lat": 26.1505, "lon": 119.9590},
]

def init_db():
    """初始化資料庫：建立表格"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS forecasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            location TEXT,
            forecast_date TEXT,
            min_temp INTEGER,
            max_temp INTEGER,
            weather_desc TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(location, forecast_date) ON CONFLICT REPLACE
        )
    ''')
    conn.commit()
    conn.close()

def save_to_db(data_list):
    """將爬蟲抓到的資料存入 SQLite data.db"""
    if not data_list:
        return
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    for item in data_list:
        c.execute('''
            INSERT INTO forecasts (location, forecast_date, min_temp, max_temp, weather_desc)
            VALUES (?, ?, ?, ?, ?)
        ''', (item['地區'], item['預報日期'], item['最低溫'], item['最高溫'], item['天氣概況']))
        
    conn.commit()
    conn.close()

def get_db_data():
    """從 SQLite data.db 讀取所有資料用於顯示"""
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql("SELECT * FROM forecasts ORDER BY location, forecast_date", conn)
    conn.close()
    return df

# 程式啟動時執行資料庫初始化
init_db()

# --- 輔助函數 ---
def find_key(node, key):
    """遞迴搜尋 JSON Key"""
    if isinstance(node, list):
        for i in node:
            result = find_key(i, key)
            if result is not None:
                return result
    elif isinstance(node, dict):
        if key in node:
            return node[key]
        for k, v in node.items():
            result = find_key(v, key)
            if result is not None:
                return result
    return None

def get_weather_icon(desc):
    """根據天氣描述回傳對應的 Emoji 圖示"""
    if not isinstance(desc, str):
        return "❓"
    
    desc_clean = desc.replace(" ", "") # 移除空白
    
    if "雷" in desc_clean:
        return "⛈️"
    if "雨" in desc_clean:
        return "🌧️"
    if "雪" in desc_clean:
        return "❄️"
    if "晴" in desc_clean and ("雲" in desc_clean or "陰" in desc_clean):
        return "⛅"
    if "晴" in desc_clean:
        return "☀️"
    if "陰" in desc_clean:
        return "☁️"
    if "雲" in desc_clean:
        return "🌥️"
    
    return "🌡️"

def get_temp_color(max_temp):
    """根據最高溫回傳顏色 (R, G, B)"""
    if max_temp >= 30:
        return [255, 87, 51]  # 熱 (紅)
    elif max_temp <= 20:
        return [51, 193, 255] # 冷 (藍)
    else:
        return [117, 255, 51] # 舒適 (綠)

# --- 爬蟲函數 ---
@st.cache_data(ttl=3600)
def fetch_and_save_weather():
    url = "https://opendata.cwa.gov.tw/fileapi/v1/opendataapi/F-A0010-001?Authorization=CWA-8DF0B9F0-1AC6-49DC-A5AD-932F40640F03&downloadType=WEB&format=JSON"
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        locations = find_key(data, 'location')
        if not locations:
            return []

        parsed_data = []
        
        for loc in locations:
            loc_name = loc.get('locationName', 'Unknown')
            weather_data = loc.get('weatherElements', {})
            if not weather_data:
                weather_data = loc.get('weatherElement', {})

            max_t_list = weather_data.get('MaxT', {}).get('daily', [])
            min_t_list = weather_data.get('MinT', {}).get('daily', [])
            wx_list = weather_data.get('Wx', {}).get('daily', [])
            
            days_count = min(len(max_t_list), len(min_t_list), len(wx_list))
            
            for i in range(days_count):
                parsed_data.append({
                    "地區": loc_name,
                    "預報日期": max_t_list[i].get('dataDate', 'N/A'),
                    "最低溫": int(min_t_list[i].get('temperature', 0)),
                    "最高溫": int(max_t_list[i].get('temperature', 0)),
                    "天氣概況": wx_list[i].get('weather', 'N/A')
                })
        
        save_to_db(parsed_data)
        return parsed_data
        
    except Exception as e:
        st.error(f"資料抓取失敗: {e}")
        return []

# --- Streamlit 主程式介面 ---

st.title("🌤️ 台灣一週農業氣象預報")
st.markdown("資料來源：交通部中央氣象署 API")

# 執行爬蟲並存檔
with st.spinner('正在同步 API 資料並寫入 SQLite data.db 資料庫...'):
    api_data = fetch_and_save_weather()

# 建立分頁 (Tabs)
tab1, tab2, tab3 = st.tabs(["📈 視覺化圖表", "🗺️ 地圖模式 (全台縣市)", "💾 本地資料庫檢視"])

# --- Tab 1: 圖表顯示區 ---
with tab1:
    if api_data:
        df = pd.DataFrame(api_data)
        
        st.sidebar.header("🔍 地區篩選")
        all_locations = df['地區'].unique().tolist()
        selected_loc = st.sidebar.selectbox("選擇地區", all_locations)
        
        filtered_df = df[df['地區'] == selected_loc]
        
        # 顯示關鍵指標
        st.subheader(f"📍 {selected_loc} - 未來天氣概況")
        if not filtered_df.empty:
            today_weather = filtered_df.iloc[0]
            
            weather_icon = get_weather_icon(today_weather['天氣概況'])
            
            col1, col2, col3 = st.columns(3)
            col1.metric("預報日期", today_weather['預報日期'])
            col2.metric("氣溫範圍", f"{today_weather['最低溫']}°C - {today_weather['最高溫']}°C")
            col3.metric("天氣概況", f"{weather_icon} {today_weather['天氣概況']}")

        # 繪製圖表
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=filtered_df['預報日期'], y=filtered_df['最高溫'], name='最高溫', line=dict(color='#FF5733')))
        fig.add_trace(go.Scatter(x=filtered_df['預報日期'], y=filtered_df['最低溫'], name='最低溫', line=dict(color='#33C1FF')))
        fig.update_layout(title=f"{selected_loc} 氣溫走勢", template="plotly_white")
        st.plotly_chart(fig, use_container_width=True)
        
    else:
        st.warning("目前沒有資料，請檢查網路連線。")

# --- Tab 2: 地圖模式區 (改良版) ---
with tab2:
    st.header("🗺️ 全台氣溫分佈圖")
    
    if api_data:
        # 原始資料 DataFrame (只有大區域)
        df_source = pd.DataFrame(api_data)
        
        # 1. 選擇日期
        available_dates = df_source['預報日期'].unique().tolist()
        selected_date = st.selectbox("📅 選擇預報日期", available_dates)
        
        # 2. 篩選該日期的原始資料
        df_day = df_source[df_source['預報日期'] == selected_date]
        
        # 3. 建立地圖用的資料 (展開到各縣市)
        map_rows = []
        for mapping in CITY_MAPPING:
            # 找到該縣市所屬的大區域資料
            region_data = df_day[df_day['地區'] == mapping['region']]
            
            if not region_data.empty:
                row_data = region_data.iloc[0].to_dict()
                # 覆寫為縣市的名稱與座標
                row_data['顯示名稱'] = mapping['city'] # 用於顯示 (如: 台北市)
                row_data['lat'] = mapping['lat']
                row_data['lon'] = mapping['lon']
                row_data['color'] = get_temp_color(row_data['最高溫'])
                map_rows.append(row_data)
        
        if map_rows:
            df_map_final = pd.DataFrame(map_rows)

            # 4. 繪製 PyDeck 地圖
            view_state = pdk.ViewState(
                latitude=23.6,
                longitude=120.9,
                zoom=6.8,
                pitch=0
            )
            
            layer = pdk.Layer(
                "ScatterplotLayer",
                df_map_final,
                get_position='[lon, lat]',
                get_color='color',
                get_radius=15000, # 圓點半徑
                pickable=True,
                opacity=0.8,
                stroked=True,
                filled=True,
                line_width_min_pixels=1,
                line_color=[255, 255, 255]
            )
            
            # 設定 Tooltip
            tooltip = {
                "html": "<b>{顯示名稱}</b> ({地區})<br/>"
                        "氣溫: {最低溫}°C - {最高溫}°C<br/>"
                        "天氣: {天氣概況}",
                "style": {
                    "backgroundColor": "steelblue",
                    "color": "white"
                }
            }
            
            r = pdk.Deck(
                layers=[layer],
                initial_view_state=view_state,
                tooltip=tooltip,
                map_style="mapbox://styles/mapbox/light-v9"
            )
            
            st.pydeck_chart(r)
            
            st.markdown(f"""
            <div style="text-align: center; margin-top: 10px;">
                <small>註：地圖上的資料為該縣市所屬<b>「大農業氣象區域」</b>的預報數值。</small>
            </div>
            <div style="display: flex; gap: 15px; justify-content: center; margin-top: 10px;">
                <div><span style="color:rgb(255, 87, 51);">●</span> 高溫 (>30°C)</div>
                <div><span style="color:rgb(117, 255, 51);">●</span> 舒適 (20-30°C)</div>
                <div><span style="color:rgb(51, 193, 255);">●</span> 低溫 (<20°C)</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.warning("無法建立地圖資料，請確認 API 是否回傳了預期的大區域資料。")
            
    else:
        st.info("無地圖資料")

# --- Tab 3: 資料庫檢視區 ---
with tab3:
    st.header("🗄️ SQLite 資料庫內容")
    st.markdown("下方表格是直接從本地檔案 `data.db` 中讀取的資料，證明資料已成功儲存。")
    
    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("🔄 重新載入資料庫"):
            st.rerun()
            
    db_df = get_db_data()
    
    if not db_df.empty:
        st.dataframe(db_df, use_container_width=True)
        st.caption(f"資料庫統計：共 {len(db_df)} 筆紀錄。")
        
        csv = db_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
        st.download_button(
            label="📥 下載資料庫 CSV",
            data=csv,
            file_name='data_db_dump.csv',
            mime='text/csv',
        )
    else:
        st.info("資料庫目前是空的，請稍候或檢查 API 連線。")