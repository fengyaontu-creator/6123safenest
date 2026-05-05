"""CSV lookup helper — C (D review)."""
import requests
import json
import os

def verify_cea_agent_status(query_type: str, query_value: str) -> dict:
    """
    供 Risk Agent 调用的外部工具：验证 CEA 中介资质。
    已根据官方最新文档修复 422 反馈功能。
    """
    dataset_id = "d_07c63be0f37e6e59c07a4ddc2fd87fcb" 
    url = "https://data.gov.sg/api/action/datastore_search"
    
    # 【根据官方文档，GET 请求使用 Accept
    headers = {
        "Accept": "*/*"
    }
    
    # 动态获取 API Key。如果你没填，依然可以尝试匿名访问（部分接口允许）
    api_key = os.getenv("DATAGOVSG_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key
    
    # resource_id 就是 dataset_id
    params = {
        "resource_id": dataset_id,
        "limit": 5 
    }
    
    # 根据官方文档：filters 是字典条件，q 也可以传入 {"columnName": "columnValue"} 格式
    if query_type == "reg_no":
        params["filters"] = json.dumps({"registration_no": query_value})
    elif query_type == "name":
        params["q"] = json.dumps({"salesperson_name": query_value})
    else:
        return {"status": "error", "message": "不支持的查询类型"}

    try:
        response = requests.get(url, params=params, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                records = data.get("result", {}).get("records", [])
                
                # 如果没查到数据，触发风险阻断
                if not records:
                    return {
                        "status": "risk", 
                        "message": f"高风险：未在官方数据库中查询到 {query_type} 为 '{query_value}' 的记录。"
                    }
                return {"status": "verified", "records": records}
            else:
                 return {"status": "error", "message": "API 请求成功，但返回 success: false"}
        else:
            # 打印详细报错内容，方便排查
            return {"status": "error", "message": f"HTTP状态码: {response.status_code}, 详情: {response.text}"}
            
    except Exception as e:
        return {"status": "error", "message": str(e)}
