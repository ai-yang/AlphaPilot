import platform

from setuptools import Extension, setup


def _pybind11_include() -> list:
    """Include dir of the pip-installed pybind11 (the previously bundled copy
    was removed: it predated Python 3.11 and no longer compiles)."""
    import pybind11

    return [pybind11.get_include()]


def get_ext_modules() -> list:
    """
    获取三方模块
    Linux和Windows需要编译封装接口
    Mac由于缺乏二进制库支持无法使用
    """
    system = platform.system()
    if system == "Darwin":
        return []

    if system == "Windows":
        extra_compile_flags = ["-O2", "-MT"]
        extra_link_args: list[str] = []
        runtime_library_dirs: list[str] = []
        md_libraries = ["emt_quote_api", "emt_trader_api_c", "emt_api"]
        td_libraries = ["emt_quote_api", "emt_trader_api_c", "emt_api"]
    else:  # Linux — link against the vendored .so in vnpy_emt/api (rpath $ORIGIN)
        extra_compile_flags = [
            "-std=c++17",
            "-O2",
            "-Wno-delete-incomplete",
            "-Wno-sign-compare",
        ]
        extra_link_args = ["-lstdc++", "-Wl,-rpath,$ORIGIN"]
        runtime_library_dirs = []
        # The new SDK splits the namespaces: quote (EMQ::API) lives in
        # libemt_quote_api.so, trade (EMT::API) in libemt_api.so.
        md_libraries = ["emt_quote_api"]
        td_libraries = ["emt_api"]

    vnemtmd = Extension(
        name="vnpy_emt.api.vnemtmd",
        sources=["vnpy_emt/api/vnemt/vnemtmd/vnemtmd.cpp"],
        define_macros=[("NOMINMAX", None)],
        include_dirs=["vnpy_emt/api/include", "vnpy_emt/api/vnemt"] + _pybind11_include(),
        library_dirs=["vnpy_emt/api/libs", "vnpy_emt/api"],
        libraries=md_libraries,
        extra_compile_args=extra_compile_flags,
        extra_link_args=extra_link_args,
        runtime_library_dirs=runtime_library_dirs,
        language="cpp",
    )

    vnemttd = Extension(
        name="vnpy_emt.api.vnemttd",
        sources=["vnpy_emt/api/vnemt/vnemttd/vnemttd.cpp"],
        define_macros=[("NOMINMAX", None)],
        include_dirs=["vnpy_emt/api/include", "vnpy_emt/api/vnemt"] + _pybind11_include(),
        library_dirs=["vnpy_emt/api/libs", "vnpy_emt/api"],
        libraries=td_libraries,
        extra_compile_args=extra_compile_flags,
        extra_link_args=extra_link_args,
        runtime_library_dirs=runtime_library_dirs,
        language="cpp",
    )

    return [vnemttd, vnemtmd]


setup(ext_modules=get_ext_modules())
