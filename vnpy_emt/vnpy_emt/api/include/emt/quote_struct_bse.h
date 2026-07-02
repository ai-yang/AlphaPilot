#pragma once

#include <cstdint>

#define IP_LEN (64)       // IP字符串地址长度定义
#define ETH_NAME_LEN (64) // Eth字符串长度定义

namespace EMQ {
namespace API {
namespace BSE {

//////////////////////////////////////////////////////////////////////////
///@brief EMQBseUdpRecvMode 是接收模式枚举
//////////////////////////////////////////////////////////////////////////
typedef enum EMQBseUdpRecvMode {
    kNormal = 0,
    kEFVI ///< solarflare efvi接收
} EMQBseUdpRecvMode;

//////////////////////////////////////////////////////////////////////////
///@brief EMQBseType 是行情类型枚举
//////////////////////////////////////////////////////////////////////////
typedef enum EMQBseType {
    kBseSnap=12      ///< 北交所快照
} EMQBseType;

//////////////////////////////////////////////////////////////////////////
///@brief EMQBseExchangeType 是交易所类型枚举
//////////////////////////////////////////////////////////////////////////
typedef enum EMQBseExchangeType {
    EMQ_EXCHANGE_BJ=3    ///< 北交所
} EMQBseExchangeType;

struct EMQUdpConfigBse {
    bool enable;                 ///< 是否启用
    EMQBseUdpRecvMode mode;            ///< 接收模式
    EMQBseType quote_type;          ///< 行情类型
    char eth_name[ETH_NAME_LEN];    ///< 网卡名
    char bind_ip[IP_LEN];          ///< 绑定地址
    uint16_t bind_port;            ///< 绑定端口（0表示系统自动分配）
    int32_t rx_cpu_id;           ///< 用于接收的cpu id，-1表示不绑定
    int32_t handle_cpu_id;       ///< 用于处理的cpu id，-1表示不绑定
    int32_t rx_pkt_num;          ///< 接收内存大小 单位为4MB
    int32_t spsc_size;           ///< 缓存队列长度，单位K

};

struct EMQLoginConfigBse{
    // Login相关参数
    char login_ip[IP_LEN];        ///< 登录服务器IP地址
    uint16_t login_port;          ///< 登录服务器端口
    char user_name[32];           ///< 用户名
    char user_pwd[32];            ///< 用户密码

};

//////////////////////////////////////////////////////////////////////////
///@brief EMQ_LOG_LEVEL 是日志级别枚举
//////////////////////////////////////////////////////////////////////////

typedef enum EMQ_LOG_LEVEL
{
    EMQ_LOG_LEVEL_TRACE,      ///< trace级别
    EMQ_LOG_LEVEL_DEBUG,     ///< debug级别
    EMQ_LOG_LEVEL_INFO,      ///< info级别
    EMQ_LOG_LEVEL_WARNING,   ///< 警告级别
    EMQ_LOG_LEVEL_ERROR,     ///< 错误级别
    EMQ_LOG_LEVEL_FATAL     ///< 严重错误级别
}EMQ_LOG_LEVEL;

} // namespace BSE
} // namespace API
} // namespace EMQ