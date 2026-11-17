from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEXES = {"000922": "中证红利", "000015": "上证红利", "000300": "沪深300", "000905": "中证500"}
CSI_URL = "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/indicator/{code}indicator.xls"
BOND_URL = "https://yield.chinabond.com.cn/cbweb-pbc-web/pbc/historyQuery"
BOND_SERIES = "chinabond_cgb_10y"
SSE_URL = "https://www.sse.com.cn/disclosure/dealinstruc/closed/"
DEFINITION = "csi_dp2_calculation_shares_dividend_window_unverified_v1"
BOND_DEFINITION = "chinabond_cgb_ytm_10y_percent_v1"

def index_series(code):
    if code not in INDEXES:
        raise ValueError(f"不支持的指数: {code}")
    return f"csi_{code}_dp2"
