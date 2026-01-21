import backend_config
import bit_api
import geekez_api


def openBrowser(browser_id):
    if backend_config.is_geekez_backend():
        return geekez_api.openBrowser(browser_id)
    return bit_api.openBrowser(browser_id)


def closeBrowser(browser_id):
    if backend_config.is_geekez_backend():
        return geekez_api.closeBrowser(browser_id)
    return bit_api.closeBrowser(browser_id)


def deleteBrowser(browser_id):
    if backend_config.is_geekez_backend():
        return geekez_api.deleteBrowser(browser_id)
    return bit_api.deleteBrowser(browser_id)
