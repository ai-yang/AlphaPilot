/////////////////////////////////////////////////////////////////////////
///@author 东方财富证券股份有限公司
///@file quote_api_lv2.h
///@brief 定义客户端Level 2行情接口
/////////////////////////////////////////////////////////////////////////

#pragma once
#include <cstdint>
#include <functional>
#include <string>
#include <vector>

#include "quote_struct_lv2.h"
#include "quote_sse_define.h"
#include "quote_sze_define.h"

namespace EMQ {
namespace API {

class QuoteSpiLv2 {
public:
    /* 以下为深交所行情回调 */

    /**
     *   深交所快照行情通知
     *   @param snap  深交所快照行情数据
     */
    virtual void OnLv2SnapSze(EMQSzeSnap *snap) {}

    /**
     *   深交所逐笔合并行情通知
     *   @param tick  深交所逐笔合并行情数据
     */
    virtual void OnLv2TickSze(EMQSzeTick *tick) {}

    /**
     *   深交所指数行情通知
     *   @param idx   深交所指数行情数据
     */
    virtual void OnLv2IndexSze(EMQSzeIdx *idx) {}

    /**
     *   深交所债券快照行情通知
     *   @param bond_snap  深交所债券快照行情数据
     */
    virtual void OnLv2BondSnapSze(EMQSzeBondSnap *bond_snap) {}

    /**
     *   深交所债券逐笔合并行情通知
     *   @param bond_tick  深交所债券逐笔合并行情数据
     */
    virtual void OnLv2BondTickSze(EMQSzeBondTick *bond_tick) {}

    /**
     *   深交所建树行情通知
     *   @param tree  深交所建树行情数据
     */
    virtual void OnLv2TreeSze(EMQSzeTree *tree) {}

    /* 以下为上交所行情回调 */

    /**
     *   上交所快照行情通知
     *   @param snap  上交所快照行情数据
     */
    virtual void OnLv2SnapSse(EMQSseSnap *snap) {}

    /**
     *   上交所逐笔合并行情通知
     *   @param tick  上交所逐笔合并行情数据
     */
    virtual void OnLv2TickSse(EMQSseTick *tick) {}

    /**
     *   上交所指数行情通知
     *   @param idx   上交所指数行情数据
     */
    virtual void OnLv2IndexSse(EMQSseIdx *idx) {}

    /**
     *   上交所债券快照行情通知
     *   @param bond_snap  上交所债券快照行情数据
     */
    virtual void OnLv2BondSnapSse(EMQSseBondSnap *bond_snap) {}

    /**
     *   上交所债券逐笔行情通知
     *   @param bond_tick  上交所债券逐笔行情数据
     */
    virtual void OnLv2BondTickSse(EMQSseBondTick *bond_tick) {}

    /**
     *   上交所建树行情通知
     *   @param tree  上交所建树行情数据
     */
    virtual void OnLv2TreeSse(EMQSseTree *tree) {}
};


#ifndef WINDOWS
#if __GNUC__ >= 4
#pragma GCC visibility push(default)
#endif
#endif

class QuoteApiLv2 {
public:
    /**
     *   创建 QuoteApiLv2 实例
     *   @param save_file_path   日志文件保存路径
     *   @param log_level        日志等级，默认为 EMQ_LOG_LEVEL_DEBUG
     *   @return                 返回创建的 QuoteApiLv2 实例
     */
    static QuoteApiLv2 *CreateQuoteApiLv2(const char *save_file_path, EMQ_LOG_LEVEL log_level = EMQ_LOG_LEVEL_DEBUG);

    /**
     *   注册回调接口
     *   @param spi  回调接口指针
     */
    virtual void RegisterSpi(QuoteSpiLv2 *spi) = 0;

    /**
     *   获取 API 版本信息
     *   @return  返回 API 版本号字符串
     */
    virtual const char *GetApiVersion() = 0;

    /**
     *   登录接口
     *   @param ip        服务器 IP 地址
     *   @param port      服务器端口
     *   @param user_name 用户名
     *   @param user_pwd  用户密码
     *   @return          登录错误码，0 表示成功，非 0 表示失败
     */
    virtual int32_t Login(const char *ip, const uint16_t port,
                          const char *user_name, const char *user_pwd) = 0;

    /**
     *   设置通道接收配置，同时进行内置系统配置最优检查
     *   @param config  通道配置数组
     *   @param num     通道数量
     *   @return        返回设置结果，0 表示成功，非 0 表示失败
     */
    virtual int32_t SetChannelConfig(EMQConfigLv2 *config, uint32_t num) = 0;

    /**
     *   启动接口
     *   @return  返回启动结果，0 表示成功，非 0 表示失败
     */
    virtual int32_t Start() = 0;

    /**
     *   停止接口
     *   @return  返回停止结果，0 表示成功，非 0 表示失败
     */
    virtual int32_t Stop() = 0;

    /**
     *   关闭接口，释放资源
     */
    virtual void Release() = 0;

    /**
     *   深市行情重建接口
     *   @param ip           服务器 IP 地址
     *   @param port         服务器端口
     *   @param spi          回调接口
     *   @param channel_num  通道编号
     *   @param begin_seq    开始序列号
     *   @param end_seq      结束序列号
     *   @return             返回重建结果，0 表示成功，非 0 表示失败
     */
    virtual int32_t RebuildQuoteSze(char *ip, uint16_t port, QuoteSpiLv2 *spi,
                                    uint32_t channel_num, uint64_t begin_seq,
                                    uint64_t end_seq) = 0;

    /**
     *   沪市行情重建接口
     *   @param ip            服务器 IP 地址
     *   @param port          服务器端口
     *   @param spi           回调接口
     *   @param category_id   数据产品类别
     *   @param trade_channel 交易通道
     *   @param begin_seq     开始序列号
     *   @param end_seq       结束序列号
     *   @return              返回重建结果，0 表示成功，非 0 表示失败
     */
    virtual int32_t RebuildQuoteSse(char *ip, uint16_t port, QuoteSpiLv2 *spi,
                                    uint32_t category_id, uint32_t trade_channel,
                                    uint64_t begin_seq, uint64_t end_seq) = 0;

    /**
     *   获取网卡收到行情包的硬件时间戳，单位 ns
     *   仅可在对应的行情 SPI 回调内调用
     *   @param packet  行情数据包
     *   @return        返回硬件接收时间戳，单位为纳秒
     */
    virtual uint64_t GetPacketHardwareRXTs(void *packet) = 0;

protected:
    virtual ~QuoteApiLv2() {}
};

#ifndef WINDOWS
#if __GNUC__ >= 4
#pragma GCC visibility pop
#endif
#endif

} // namespace API
} // namespace EMQ