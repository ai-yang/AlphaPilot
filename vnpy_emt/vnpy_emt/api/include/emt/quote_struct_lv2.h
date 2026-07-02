#pragma once

#include <cstdint>

#define IP_LEN (64)       // IP字符串地址长度定义
#define ETH_NAME_LEN (64) // Eth字符串长度定义

namespace EMQ {
namespace API {

//////////////////////////////////////////////////////////////////////////
///@brief EMQRecvMode 是接收模式枚举
//////////////////////////////////////////////////////////////////////////
typedef enum EMQRecvMode {
    kNormal = 0,
    kEFVI, ///< solarflare efvi接收
} EMQRecvMode;

//////////////////////////////////////////////////////////////////////////
///@brief EMQType 是行情类型枚举
//////////////////////////////////////////////////////////////////////////
typedef enum EMQType {
    kSzeSnap = 0, ///< 深交所快照
    kSzeTick,     ///< 深交所逐笔
    kSzeIndex,    ///< 深交所指数
    kSzeBondSnap, ///< 深交所债券快照
    kSzeBondTick, ///< 深交所债券逐笔
    kSzeTree,     ///< 深交所建树
    kSseSnap,     ///< 上交所快照
    kSseTick,     ///< 上交所逐笔
    kSseIndex,    ///< 上交所指数
    kSseBondSnap, ///< 上交所债券快照
    kSseBondTick, ///< 上交所债券逐笔
    kSseTree,     ///< 上交所建树
} EMQType;

//////////////////////////////////////////////////////////////////////////
///@brief EMQExchangeType 是交易所类型枚举
//////////////////////////////////////////////////////////////////////////
typedef enum EMQExchangeType {
    EMQ_EXCHANGE_SH = 1, ///< 上交所
    EMQ_EXCHANGE_SZ,     ///< 深交所
} EMQExchangeType;

struct EMQConfigLv2 {
    bool enable;                 ///< 是否启用
    EMQRecvMode mode;            ///< 接收模式
    EMQType quote_type;          ///< 行情类型
    char eth_name[ETH_NAME_LEN]; ///< 网卡名
    char multicast_ip[IP_LEN];   ///< 组播地址
    uint16_t multicast_port;     ///< 组播端口
    int32_t rx_cpu_id;           ///< 用于接收的cpu id，-1表示不绑定
    int32_t handle_cpu_id;       ///< 用于处理的cpu id，-1表示不绑定
    int32_t rx_pkt_num;          ///< 接收内存大小 单位为4MB
    int32_t spsc_size;           ///< 缓存队列长度，单位K
};

//////////////////////////////////////////////////////////////////////////
///@brief EMQ_LOG_LEVEL 是日志级别枚举
//////////////////////////////////////////////////////////////////////////
typedef enum EMQ_LOG_LEVEL
{
    EMQ_LOG_LEVEL_FATAL,     ///< 严重错误级别
    EMQ_LOG_LEVEL_ERROR,     ///< 错误级别
    EMQ_LOG_LEVEL_WARNING,   ///< 警告级别
    EMQ_LOG_LEVEL_INFO,      ///< info级别
    EMQ_LOG_LEVEL_DEBUG,     ///< debug级别
    EMQ_LOG_LEVEL_TRACE      ///< trace级别
}EMQ_LOG_LEVEL;

} // namespace API
} // namespace EMQ