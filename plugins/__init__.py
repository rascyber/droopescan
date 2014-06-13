from cement.core import handler, controller
from common import logger
from datetime import datetime
import common
import requests
from requests_futures.sessions import FuturesSession

class BasePlugin(controller.CementBaseController):

    valid_enumerate = ['u', 'p', 't', 'a']
    class ScanningMethod():
        not_found = 404
        forbidden = 403
        ok = 200

    class Meta:
        label = 'baseplugin'
        stacked_on = 'base'

        arguments = []

    def _options(self):
        pargs = self.app.pargs

        url = common.validate_url(pargs.url)
        method = pargs.method

        number = pargs.number if pargs.number else 1000
        threads = pargs.threads if pargs.threads else 10
        plugins_base_url = pargs.plugins_base_url if pargs.plugins_base_url \
            else self.plugins_base_url
        themes_base_url = pargs.themes_base_url if pargs.themes_base_url \
                else self.themes_base_url

        enumerate = pargs.enumerate
        if enumerate:
            common.validate_enumerate(enumerate, self.valid_enumerate)
        else:
            enumerate = 'a'

        if method:
            scanning_method = common.validate_method(method, self.ScanningMethod)
        else:
            scanning_method = self.determine_scanning_method(url)

        # all variables here will be returned.
        return locals()

    def _functionality(self, opts):

        all = {
                "plugins":  {
                    "func": getattr(self, "enumerate_plugins"),
                    "base_url": opts['plugins_base_url']
                },
                "users": {
                    "func": getattr(self, "enumerate_users"),
                    "base_url": None,
                },
                "themes": {
                    "func": getattr(self, "enumerate_themes"),
                    "base_url": opts['themes_base_url']
                }
            }

        functionality = {}
        if opts['enumerate'] == "p":
            functionality['plugins'] = all['plugins']
        elif opts['enumerate'] == "t":
            functionality['themes'] = all['themes']
        elif opts['enumerate'] == "u":
            functionality['users'] = all['users']
        elif opts['enumerate'] == "a":
            functionality = all

        return functionality

    def enumerate_route(self):
        time_start = datetime.now()
        opts = self._options()
        functionality = self._functionality(opts)

        enumerating_all = opts['enumerate'] == 'a'
        if enumerating_all:
            common.echo(common.template('scan_begin.tpl', {'noun': 'all', 'url':
                opts['url']}))

        # The loop of enumeration.
        for enumerate in functionality:
            try:
                if not enumerating_all:
                    common.echo(common.template("scan_begin.tpl", {"noun": enumerate,
                        "url": opts['url']}))

                enum = functionality[enumerate]
                finds = enum["func"](opts['url'], enum["base_url"],
                        opts['scanning_method'], opts['number'], opts['threads'])

                template_params = {
                        "noun": enumerate,
                        "Noun": enumerate.capitalize(),
                        "items": self.finds_process(opts['url'], finds),
                        "empty": len(finds) == 0,
                    }

                common.echo(common.template("list_noun.tpl", template_params))

            except RuntimeError, e:
                # some kinds of enumeration might not be available for this
                # plugin.
                if enumerating_all:
                    pass
                else:
                    raise

        common.echo("\033[95m[+] Scan finished (%s elapsed)\033[0m" % str(datetime.now() - time_start))

    def determine_scanning_method(self, url):
        folder_resp = requests.get(url + self.folder_url)

        if common.is_string(self.regular_file_url):
            ok_resp = requests.get(url + self.regular_file_url)
            ok_200 = ok_resp.status_code == 200
        else:
            ok_200 = False
            for path in self.regular_file_url:
                ok_resp = requests.get(url + path)
                if ok_resp.status_code == 200:
                    ok_200 = True
                    break

        if folder_resp.status_code == 403 and ok_200:
            return self.ScanningMethod.forbidden
        if folder_resp.status_code == 404 and ok_200:
            logger.warning("Known %s folders have returned 404 Not Found. If modules do not have a %s file they will not be detected." %
                    (self._meta.label, self.module_readme_file))
            return self.ScanningMethod.not_found
        if folder_resp.status_code == 200 and ok_200:
            logger.warning("""Known folder names for %s are returning 200 OK. Is directory listing enabled?""" % self._meta.label)
            return self.ScanningMethod.ok
        else:
            raise RuntimeError("""It is possible that the website is not running %s. If you disagree, please specify a --method.""" %
                    self._meta.label)

    def plugins_get(self, amount=100000):
        amount = int(amount)
        with open(self.plugins_file) as f:
            i = 0
            for plugin in f:
                if i >= amount:
                    break
                yield plugin.strip()
                i += 1

    def themes_get(self, amount=100000):
        amount = int(amount)
        with open(self.themes_file) as f:
            i = 0
            for theme in f:
                if i>= amount:
                    break
                yield theme.strip()
                i +=1

    def enumerate(self, url, base_url_supplied, scanning_method, iterator_returning_method, max_iterator=500, threads=10):
        """
            @param url base URL for the website.
            @param base_url_supplied Base url for themes, plugins. E.g. '%ssites/all/modules/%s/'
            @param scanning_method see self.ScanningMethod
            @param iterator_returning_method a function which returns an
                element that, when iterated, will return a full list of plugins
            @param max_iterator integer that will be passed unto iterator_returning_method
        """
        if common.is_string(base_url_supplied):
            base_urls = [base_url_supplied]
        else:
            base_urls = base_url_supplied

        found = {}
        for base_url in base_urls:
            found[base_url] = []
            plugins = iterator_returning_method(max_iterator)

            if scanning_method == self.ScanningMethod.not_found:
                url_template = base_url + self.module_readme_file
                expected_status = 200
            else:
                url_template = base_url
                expected_status = scanning_method

            sess = FuturesSession(max_workers=int(threads))
            futures = {}
            for plugin in plugins:
                f = sess.get(url_template % (url, plugin))
                futures[plugin] = f

            for plugin_name in futures:
                r = futures[plugin_name].result()
                if r.status_code == expected_status:
                    found[base_url].append(plugin_name)

        return found

    def enumerate_plugins(self, url, base_url, scanning_method=403, max_plugins=500, threads=10):
        iterator = getattr(self, "plugins_get")
        return self.enumerate(url, base_url, scanning_method, iterator, max_plugins, threads)

    def enumerate_themes(self, url, base_url, scanning_method=403, max_plugins=500, threads=10):
        iterator = getattr(self, "themes_get")
        return self.enumerate(url, base_url, scanning_method, iterator, max_plugins, threads)

    def enumerate_users(self, url, base_url, scanning_method=403, max_plugins=500, threads=10):
        raise NotImplementedError("Not implemented yet.")

    def finds_process(self, url, finds):
        final = []
        for path in finds:
            for module in finds[path]:
                final.append({
                        'name': module,
                        'url': path % (url, module),
                    })

        return final
