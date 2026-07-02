// vnemtmd.cpp : minimal-surface EMT quote binding against the new EMQ::API SDK.
// Callbacks acquire the GIL and dispatch dicts directly (same pattern as the
// old binding and vnpy's other gateway wrappers).
#ifdef WIN32
#include "pch.h"
#endif
#include "vnemtmd.h"


// GBK/GB18030 -> UTF-8, tolerant of a missing zh locale (returns raw bytes
// replaced by '?' on failure instead of throwing into the SDK callback thread).
static string toUtfSafe(const char* raw)
{
	if (!raw)
	{
		return string();
	}
	try
	{
		return toUtf(string(raw));
	}
	catch (...)
	{
		string fallback(raw);
		for (auto& ch : fallback)
		{
			if (static_cast<unsigned char>(ch) > 0x7F)
			{
				ch = '?';
			}
		}
		return fallback;
	}
}


//-------------------------------------------------------------------------------------
// C++ SPI overrides
//-------------------------------------------------------------------------------------

void MdApi::OnError(const EMTRspInfoStruct* error_info)
{
	gil_scoped_acquire acquire;
	dict error;
	if (error_info)
	{
		this->last_error_id = error_info->error_id;
		this->last_error_msg = toUtfSafe(error_info->error_msg);
		error["error_id"] = error_info->error_id;
		error["error_msg"] = this->last_error_msg;
	}
	this->onError(error);
};

void MdApi::OnDepthMarketData(EMTMarketDataStruct* market_data, int64_t bid1_qty[], int32_t bid1_count, int32_t max_bid1_count, int64_t ask1_qty[], int32_t ask1_count, int32_t max_ask1_count)
{
	gil_scoped_acquire acquire;
	dict data;
	if (market_data)
	{
		data["exchange_id"] = (int)market_data->exchange_id;
		data["ticker"] = market_data->ticker;
		data["last_price"] = market_data->last_price;
		data["pre_close_price"] = market_data->pre_close_price;
		data["open_price"] = market_data->open_price;
		data["high_price"] = market_data->high_price;
		data["low_price"] = market_data->low_price;
		data["close_price"] = market_data->close_price;
		data["upper_limit_price"] = market_data->upper_limit_price;
		data["lower_limit_price"] = market_data->lower_limit_price;
		data["data_time"] = market_data->data_time;
		data["qty"] = market_data->qty;
		data["turnover"] = market_data->turnover;
		data["avg_price"] = market_data->avg_price;
		data["trades_count"] = market_data->trades_count;
		data["ticker_status"] = market_data->ticker_status;
		data["total_bid_qty"] = market_data->total_bid_qty;
		data["total_ask_qty"] = market_data->total_ask_qty;
		data["ma_bid_price"] = market_data->ma_bid_price;
		data["ma_ask_price"] = market_data->ma_ask_price;
		data["data_type"] = (int)market_data->data_type;

		pybind11::list bid;
		pybind11::list ask;
		pybind11::list bid_qty;
		pybind11::list ask_qty;
		for (int i = 0; i < 10; i++)
		{
			bid.append(market_data->bid[i]);
			ask.append(market_data->ask[i]);
			bid_qty.append(market_data->bid_qty[i]);
			ask_qty.append(market_data->ask_qty[i]);
		}
		data["bid"] = bid;
		data["ask"] = ask;
		data["bid_qty"] = bid_qty;
		data["ask_qty"] = ask_qty;
	}
	this->onDepthMarketData(data);
};

void MdApi::OnIndexData(EMTIndexDataStruct* index_data)
{
	gil_scoped_acquire acquire;
	dict data;
	if (index_data)
	{
		data["exchange_id"] = (int)index_data->exchange_id;
		data["ticker"] = index_data->ticker;
		data["data_time"] = index_data->data_time;
		data["pre_close_price"] = index_data->pre_close_price;
		data["open_price"] = index_data->open_price;
		data["last_price"] = index_data->last_price;
		data["high_price"] = index_data->high_price;
		data["low_price"] = index_data->low_price;
		data["qty"] = index_data->qty;
		data["turnover"] = index_data->turnover;
	}
	this->onIndexData(data);
};

static void fillTickerDicts(EMTSpecificTickerStruct* ticker, EMTRspInfoStruct* error_info, dict& data, dict& error)
{
	if (ticker)
	{
		data["exchange_id"] = (int)ticker->exchange_id;
		data["ticker"] = ticker->ticker;
	}
	if (error_info)
	{
		error["error_id"] = error_info->error_id;
		error["error_msg"] = toUtfSafe(error_info->error_msg);
	}
}

void MdApi::OnSubMarketData(EMTSpecificTickerStruct* ticker, EMTRspInfoStruct* error_info, bool is_last)
{
	gil_scoped_acquire acquire;
	dict data;
	dict error;
	fillTickerDicts(ticker, error_info, data, error);
	this->onSubMarketData(data, error, is_last);
};

void MdApi::OnUnSubMarketData(EMTSpecificTickerStruct* ticker, EMTRspInfoStruct* error_info, bool is_last)
{
	gil_scoped_acquire acquire;
	dict data;
	dict error;
	fillTickerDicts(ticker, error_info, data, error);
	this->onUnSubMarketData(data, error, is_last);
};

void MdApi::OnSubscribeAllMarketData(EMQ_EXCHANGE_TYPE exchange_id, EMTRspInfoStruct* error_info)
{
	gil_scoped_acquire acquire;
	dict data;
	dict error;
	fillTickerDicts(NULL, error_info, data, error);
	this->onSubscribeAllMarketData((int)exchange_id, error);
};

void MdApi::OnUnSubscribeAllMarketData(EMQ_EXCHANGE_TYPE exchange_id, EMTRspInfoStruct* error_info)
{
	gil_scoped_acquire acquire;
	dict data;
	dict error;
	fillTickerDicts(NULL, error_info, data, error);
	this->onUnSubscribeAllMarketData((int)exchange_id, error);
};

void MdApi::OnSubIndexData(EMTSpecificTickerStruct* ticker, EMTRspInfoStruct* error_info, bool is_last)
{
	gil_scoped_acquire acquire;
	dict data;
	dict error;
	fillTickerDicts(ticker, error_info, data, error);
	this->onSubIndexData(data, error, is_last);
};

void MdApi::OnUnSubIndexData(EMTSpecificTickerStruct* ticker, EMTRspInfoStruct* error_info, bool is_last)
{
	gil_scoped_acquire acquire;
	dict data;
	dict error;
	fillTickerDicts(ticker, error_info, data, error);
	this->onUnSubIndexData(data, error, is_last);
};

void MdApi::OnSubscribeAllIndexData(EMQ_EXCHANGE_TYPE exchange_id, EMTRspInfoStruct* error_info)
{
	gil_scoped_acquire acquire;
	dict data;
	dict error;
	fillTickerDicts(NULL, error_info, data, error);
	this->onSubscribeAllIndexData((int)exchange_id, error);
};

void MdApi::OnUnSubscribeAllIndexData(EMQ_EXCHANGE_TYPE exchange_id, EMTRspInfoStruct* error_info)
{
	gil_scoped_acquire acquire;
	dict data;
	dict error;
	fillTickerDicts(NULL, error_info, data, error);
	this->onUnSubscribeAllIndexData((int)exchange_id, error);
};

void MdApi::OnQueryAllTickers(EMTQuoteStaticInfo* qsi, EMTRspInfoStruct* error_info, bool is_last)
{
	gil_scoped_acquire acquire;
	dict data;
	dict error;
	if (qsi)
	{
		data["exchange_id"] = (int)qsi->exchange_id;
		data["ticker"] = qsi->ticker;
		data["ticker_name"] = toUtfSafe(qsi->ticker_name);
		data["ticker_type"] = (int)qsi->ticker_type;
		data["pre_close_price"] = qsi->pre_close_price;
		data["upper_limit_price"] = qsi->upper_limit_price;
		data["lower_limit_price"] = qsi->lower_limit_price;
		data["price_tick"] = qsi->price_tick;
		data["buy_qty_unit"] = qsi->buy_qty_unit;
		data["sell_qty_unit"] = qsi->sell_qty_unit;
	}
	if (error_info)
	{
		error["error_id"] = error_info->error_id;
		error["error_msg"] = toUtfSafe(error_info->error_msg);
	}
	this->onQueryAllTickers(data, error, is_last);
};

void MdApi::OnQueryAllTickersFullInfo(EMTQuoteFullInfo* qfi, EMTRspInfoStruct* error_info, bool is_last)
{
	gil_scoped_acquire acquire;
	dict data;
	dict error;
	if (qfi)
	{
		data["exchange_id"] = (int)qfi->exchange_id;
		data["ticker"] = qfi->ticker;
		data["ticker_name"] = toUtfSafe(qfi->ticker_name);
		data["security_type"] = (int)qfi->security_type;
		data["ticker_qualification_class"] = (int)qfi->ticker_qualification_class;
		data["is_have_price_limit"] = qfi->is_have_price_limit;
		data["upper_limit_price"] = qfi->upper_limit_price;
		data["lower_limit_price"] = qfi->lower_limit_price;
		data["pre_close_price"] = qfi->pre_close_price;
		data["price_tick"] = qfi->price_tick;
		data["bid_qty_upper_limit"] = qfi->bid_qty_upper_limit;
		data["bid_qty_lower_limit"] = qfi->bid_qty_lower_limit;
		data["bid_qty_unit"] = qfi->bid_qty_unit;
		data["ask_qty_upper_limit"] = qfi->ask_qty_upper_limit;
		data["ask_qty_lower_limit"] = qfi->ask_qty_lower_limit;
		data["ask_qty_unit"] = qfi->ask_qty_unit;
	}
	if (error_info)
	{
		error["error_id"] = error_info->error_id;
		error["error_msg"] = toUtfSafe(error_info->error_msg);
	}
	this->onQueryAllTickersFullInfo(data, error, is_last);
};

void MdApi::OnQueryTickersPriceInfo(EMTTickerPriceInfo* price_info, EMTRspInfoStruct* error_info, bool is_last)
{
	gil_scoped_acquire acquire;
	dict data;
	dict error;
	if (price_info)
	{
		data["exchange_id"] = (int)price_info->exchange_type;
		data["ticker"] = price_info->ticker;
		data["last_price"] = price_info->last_price;
	}
	if (error_info)
	{
		error["error_id"] = error_info->error_id;
		error["error_msg"] = toUtfSafe(error_info->error_msg);
	}
	this->onQueryTickersPriceInfo(data, error, is_last);
};


//-------------------------------------------------------------------------------------
// Request methods
//-------------------------------------------------------------------------------------

void MdApi::createQuoteApi(string log_path, int log_file_level, int log_console_level)
{
	if (!this->api)
	{
		this->api = QuoteApi::CreateQuoteApi(log_path.c_str(), (EMQ_LOG_LEVEL)log_file_level, (EMQ_LOG_LEVEL)log_console_level);
		this->api->RegisterSpi(this);
		this->active = true;
	}
};

void MdApi::init()
{
	// Kept for interface compatibility with the old binding; the new SDK needs
	// no explicit start step beyond CreateQuoteApi + Login.
};

void MdApi::release()
{
	this->exit();
};

int MdApi::exit()
{
	if (this->api && this->active)
	{
		this->active = false;
		this->api->Logout();
		// The new QuoteApi exposes no Release(); the instance is intentionally
		// kept alive (SDK worker threads may still reference it during teardown).
		this->api = NULL;
	}
	return 1;
};

int MdApi::login(string ip, int port, string user, string password)
{
	int i = this->api->Login(ip.c_str(), (uint16_t)port, user.c_str(), password.c_str());
	if (i != 0)
	{
		this->last_error_id = i;
		this->last_error_msg = "quote login failed, return code " + to_string(i);
	}
	return i;
};

int MdApi::logout()
{
	if (this->api)
	{
		this->api->Logout();
	}
	return 0;
};

int MdApi::subscribeMarketData(string ticker, int count, int exchange_id)
{
	char* buffer = (char*)ticker.c_str();
	char* myreq[1] = { buffer };
	return this->api->SubscribeMarketData(myreq, 1, (EMQ_EXCHANGE_TYPE)exchange_id);
};

int MdApi::unSubscribeMarketData(string ticker, int count, int exchange_id)
{
	char* buffer = (char*)ticker.c_str();
	char* myreq[1] = { buffer };
	return this->api->UnSubscribeMarketData(myreq, 1, (EMQ_EXCHANGE_TYPE)exchange_id);
};

int MdApi::subscribeAllMarketData(int exchange_id)
{
	return this->api->SubscribeAllMarketData((EMQ_EXCHANGE_TYPE)exchange_id);
};

int MdApi::unSubscribeAllMarketData(int exchange_id)
{
	return this->api->UnSubscribeAllMarketData((EMQ_EXCHANGE_TYPE)exchange_id);
};

int MdApi::subscribeIndexData(string ticker, int count, int exchange_id)
{
	char* buffer = (char*)ticker.c_str();
	char* myreq[1] = { buffer };
	return this->api->SubscribeIndexData(myreq, 1, (EMQ_EXCHANGE_TYPE)exchange_id);
};

int MdApi::unSubscribeIndexData(string ticker, int count, int exchange_id)
{
	char* buffer = (char*)ticker.c_str();
	char* myreq[1] = { buffer };
	return this->api->UnSubscribeIndexData(myreq, 1, (EMQ_EXCHANGE_TYPE)exchange_id);
};

int MdApi::subscribeAllIndexData(int exchange_id)
{
	return this->api->SubscribeAllIndexData((EMQ_EXCHANGE_TYPE)exchange_id);
};

int MdApi::unSubscribeAllIndexData(int exchange_id)
{
	return this->api->UnSubscribeAllIndexData((EMQ_EXCHANGE_TYPE)exchange_id);
};

int MdApi::queryAllTickers(int exchange_id)
{
	return this->api->QueryAllTickers((EMQ_EXCHANGE_TYPE)exchange_id);
};

int MdApi::queryAllTickersFullInfo(int exchange_id)
{
	return this->api->QueryAllTickersFullInfo((EMQ_EXCHANGE_TYPE)exchange_id);
};

int MdApi::queryTickersPriceInfo(string ticker, int count, int exchange_id)
{
	char* buffer = (char*)ticker.c_str();
	char* myreq[1] = { buffer };
	return this->api->QueryTickersPriceInfo(myreq, 1, (EMQ_EXCHANGE_TYPE)exchange_id);
};

dict MdApi::getApiLastError()
{
	gil_scoped_acquire acquire;
	dict error;
	error["error_id"] = this->last_error_id;
	error["error_msg"] = this->last_error_msg;
	return error;
};


//-------------------------------------------------------------------------------------
// pybind11 trampoline + module
//-------------------------------------------------------------------------------------

class PyMdApi : public MdApi
{
public:
	using MdApi::MdApi;

	void onDisconnected(int reason) override
	{
		try { PYBIND11_OVERLOAD(void, MdApi, onDisconnected, reason); }
		catch (const error_already_set& e) { cout << e.what() << endl; }
	};

	void onError(const dict& data) override
	{
		try { PYBIND11_OVERLOAD(void, MdApi, onError, data); }
		catch (const error_already_set& e) { cout << e.what() << endl; }
	};

	void onDepthMarketData(const dict& data) override
	{
		try { PYBIND11_OVERLOAD(void, MdApi, onDepthMarketData, data); }
		catch (const error_already_set& e) { cout << e.what() << endl; }
	};

	void onIndexData(const dict& data) override
	{
		try { PYBIND11_OVERLOAD(void, MdApi, onIndexData, data); }
		catch (const error_already_set& e) { cout << e.what() << endl; }
	};

	void onSubMarketData(const dict& data, const dict& error, bool is_last) override
	{
		try { PYBIND11_OVERLOAD(void, MdApi, onSubMarketData, data, error, is_last); }
		catch (const error_already_set& e) { cout << e.what() << endl; }
	};

	void onUnSubMarketData(const dict& data, const dict& error, bool is_last) override
	{
		try { PYBIND11_OVERLOAD(void, MdApi, onUnSubMarketData, data, error, is_last); }
		catch (const error_already_set& e) { cout << e.what() << endl; }
	};

	void onSubscribeAllMarketData(int exchange_id, const dict& error) override
	{
		try { PYBIND11_OVERLOAD(void, MdApi, onSubscribeAllMarketData, exchange_id, error); }
		catch (const error_already_set& e) { cout << e.what() << endl; }
	};

	void onUnSubscribeAllMarketData(int exchange_id, const dict& error) override
	{
		try { PYBIND11_OVERLOAD(void, MdApi, onUnSubscribeAllMarketData, exchange_id, error); }
		catch (const error_already_set& e) { cout << e.what() << endl; }
	};

	void onSubIndexData(const dict& data, const dict& error, bool is_last) override
	{
		try { PYBIND11_OVERLOAD(void, MdApi, onSubIndexData, data, error, is_last); }
		catch (const error_already_set& e) { cout << e.what() << endl; }
	};

	void onUnSubIndexData(const dict& data, const dict& error, bool is_last) override
	{
		try { PYBIND11_OVERLOAD(void, MdApi, onUnSubIndexData, data, error, is_last); }
		catch (const error_already_set& e) { cout << e.what() << endl; }
	};

	void onSubscribeAllIndexData(int exchange_id, const dict& error) override
	{
		try { PYBIND11_OVERLOAD(void, MdApi, onSubscribeAllIndexData, exchange_id, error); }
		catch (const error_already_set& e) { cout << e.what() << endl; }
	};

	void onUnSubscribeAllIndexData(int exchange_id, const dict& error) override
	{
		try { PYBIND11_OVERLOAD(void, MdApi, onUnSubscribeAllIndexData, exchange_id, error); }
		catch (const error_already_set& e) { cout << e.what() << endl; }
	};

	void onQueryAllTickers(const dict& data, const dict& error, bool is_last) override
	{
		try { PYBIND11_OVERLOAD(void, MdApi, onQueryAllTickers, data, error, is_last); }
		catch (const error_already_set& e) { cout << e.what() << endl; }
	};

	void onQueryAllTickersFullInfo(const dict& data, const dict& error, bool is_last) override
	{
		try { PYBIND11_OVERLOAD(void, MdApi, onQueryAllTickersFullInfo, data, error, is_last); }
		catch (const error_already_set& e) { cout << e.what() << endl; }
	};

	void onQueryTickersPriceInfo(const dict& data, const dict& error, bool is_last) override
	{
		try { PYBIND11_OVERLOAD(void, MdApi, onQueryTickersPriceInfo, data, error, is_last); }
		catch (const error_already_set& e) { cout << e.what() << endl; }
	};
};


PYBIND11_MODULE(vnemtmd, m)
{
	class_<MdApi, PyMdApi> mdapi(m, "MdApi", module_local());
	mdapi
		.def(init<>())
		.def("createQuoteApi", &MdApi::createQuoteApi)
		.def("init", &MdApi::init)
		.def("release", &MdApi::release)
		.def("exit", &MdApi::exit)
		.def("getApiLastError", &MdApi::getApiLastError)
		.def("login", &MdApi::login)
		.def("logout", &MdApi::logout)
		.def("subscribeMarketData", &MdApi::subscribeMarketData)
		.def("unSubscribeMarketData", &MdApi::unSubscribeMarketData)
		.def("subscribeAllMarketData", &MdApi::subscribeAllMarketData)
		.def("unSubscribeAllMarketData", &MdApi::unSubscribeAllMarketData)
		.def("subscribeIndexData", &MdApi::subscribeIndexData)
		.def("unSubscribeIndexData", &MdApi::unSubscribeIndexData)
		.def("subscribeAllIndexData", &MdApi::subscribeAllIndexData)
		.def("unSubscribeAllIndexData", &MdApi::unSubscribeAllIndexData)
		.def("queryAllTickers", &MdApi::queryAllTickers)
		.def("queryAllTickersFullInfo", &MdApi::queryAllTickersFullInfo)
		.def("queryTickersPriceInfo", &MdApi::queryTickersPriceInfo)

		.def("onDisconnected", &MdApi::onDisconnected)
		.def("onError", &MdApi::onError)
		.def("onDepthMarketData", &MdApi::onDepthMarketData)
		.def("onIndexData", &MdApi::onIndexData)
		.def("onSubMarketData", &MdApi::onSubMarketData)
		.def("onUnSubMarketData", &MdApi::onUnSubMarketData)
		.def("onSubscribeAllMarketData", &MdApi::onSubscribeAllMarketData)
		.def("onUnSubscribeAllMarketData", &MdApi::onUnSubscribeAllMarketData)
		.def("onSubIndexData", &MdApi::onSubIndexData)
		.def("onUnSubIndexData", &MdApi::onUnSubIndexData)
		.def("onSubscribeAllIndexData", &MdApi::onSubscribeAllIndexData)
		.def("onUnSubscribeAllIndexData", &MdApi::onUnSubscribeAllIndexData)
		.def("onQueryAllTickers", &MdApi::onQueryAllTickers)
		.def("onQueryAllTickersFullInfo", &MdApi::onQueryAllTickersFullInfo)
		.def("onQueryTickersPriceInfo", &MdApi::onQueryTickersPriceInfo)
		;
}
