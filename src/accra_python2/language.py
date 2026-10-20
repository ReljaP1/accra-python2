from accra_language import Config, EnvironmentManager, Language, LanguageSpec

from .pip_env import Pip


class Python2(Language):
    def __init__(self, config: Config, env_manager: EnvironmentManager | None = None):
        spec = LanguageSpec(
            name="python2",
            version="2",
            config=config,
            supported_env_managers={Pip(config)},
        )
        super().__init__(spec, env_manager=env_manager)
