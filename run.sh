
# 当任何命令执行失败时，立即退出脚本
set -e

# 获取脚本所在的目录，并切换到该目录
# 这使得脚本可以从任何位置被调用
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

export NFOFETCH_BROWSE_ROOT=/home/syaofox/Videos
export NFOFETCH_JAVDB_COOKIE='theme=auto; over18=1; list_mode=v; _ym_uid=178178079810187426; _ym_d=1781780798; _ym_isad=2; _rucaptcha_session_id=f5ce662311e81466dd1485cef6ed16db; cf_clearance=eoEtBmhv4_rf.mXo0MZ3R2lLuhpAs1ks18s_L0HM.qQ-1782111992-1.2.1.1-.PxkMkV5e.Qv93oF9XA52b7_7_ZWpPYwUpIlwHqRcgBzIXCk2S2k_hdmPCm_UzDYZ3FEv43qvy5bMHaIlbPFhJsHUZkYTcUiYgYUMdOD2hnphhNWTDp_dcuaTTSW22zSk_khLRSvOpcYyuHOrzl_kuPye5yTlYVkPmvNiuCPhUIb_xrWIUeVK8LnEKMxqMu.2u7rAjrmw.d6Sr8pZgcJd.0c9jo2mpwxprxWUWxrhki5oz7K3nW3y3Ao7N7i6Y2Jx.TcdrZmDV9f.EN_nVVgz8UjVfZ_1sd.UpsL69uW3QfVqkqINJDXDMOAV6VK_Ba15mL3JNz9i53DHOzw7EKu3g; redirect_to=%2Fv%2Fbq7bA; remember_me_token=eyJfcmFpbHMiOnsibWVzc2FnZSI6IklqWnhUWGREZFVKNFptMWphSFpoYjNkNFlXRkVJZz09IiwiZXhwIjoiMjAyNi0wNi0yOVQwNzowNzo1NS4wMDBaIiwicHVyIjoiY29va2llLnJlbWVtYmVyX21lX3Rva2VuIn19--e741c485cd9776f41641a4958054b4447261e11e; locale=zh-CN; _jdb_session=NdIeHTQZ1m0QjyYcOHkxMJyzQBT9kS0gM9wHb4knrpPCJ8ZnpRjsxpvsrjeKxj7jBDBYMy5KPkUjj%2FGPidEk7JpXFWu%2F5qbAwgsmLF7Bb8w%2FEP6RVIn3DgjyuTLd%2BTpcc8paw1qK53xm07FjlD1IevzooInqxSPEDwWcSnG08Z3xwjfwmm3VnJxVyyj79rJehK%2BmfY1dPZwHNM784UrOdOA9bpQHJWWkSM2qrm4UnTLjp0WY7rUqNATM8ZLkwKbtgRf33FT9pFeWjdz0n0eHt1QlMR3wgVjZ61BY2%2Fi1gQuWTeYtMJSIivFgmghl3uHrXNsUjbUGt53sjeqyeo8wCafMBk%2FawEjeWqTds11MrdZQumt4r%2FDoHYFMTY6bhqzkKow%3D--Gh6Vt8iw2vdmmBxy--WvqdcDLetfUei%2BtK9Vovgw%3D%3D'
export NFOFETCH_DMM_COOKIE='top_dummy=a0f8a48d-4d7d-4382-b839-3557c35010c3; i3_ab=212c2edc-3b9e-4f26-9f64-698cce1aeeb2; age_check_done=1; top_pv_uid=85d6777b-23e0-4f0a-a169-b88552256cf9; ckcy=1; is_intarnal=true; ckcy=1; list_condition=%7B%22digital%22%3A%7B%22limit%22%3Anull%2C%22sort%22%3Anull%2C%22view%22%3Anull%7D%7D; dig_history=kavr00501%2Cpxvrg00005; _dd_s=rum=0&expire=1782447434610'
export NFOFETCH_LOG_LEVEL=INFO
export NFOFETCH_SERIAL_WRITES=true

uv run uvicorn app.main:app --reload
