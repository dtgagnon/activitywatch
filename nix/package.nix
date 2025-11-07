{ lib
, python311
, poetry-core
, buildPythonApplication
, fetchFromGitHub
, makeWrapper
, # Python dependencies
  requests
, pyyaml
, click
, openai
, watchdog
, pydantic
, sqlalchemy
, # aw-client and aw-core (local paths)
, aw-client ? null
, aw-core ? null
}:

buildPythonApplication rec {
  pname = "aw-llm-worker";
  version = "0.1.0";
  format = "pyproject";

  src = lib.cleanSource ../.;

  nativeBuildInputs = [
    poetry-core
    makeWrapper
  ];

  propagatedBuildInputs = [
    # Core dependencies
    requests
    pyyaml
    click
    # LLM clients
    openai
    # Config hot-reload
    watchdog
    # Data validation
    pydantic
    # Caching
    sqlalchemy
  ] ++ lib.optionals (aw-client != null) [ aw-client ]
    ++ lib.optionals (aw-core != null) [ aw-core ];

  # The package includes local dependencies via path in pyproject.toml
  # When building with Nix, we need to handle these specially
  preBuild = ''
    # If aw-client and aw-core are provided as Nix packages, we use those
    # Otherwise, we expect them to be in activitywatch_src/
    ${lib.optionalString (aw-client == null) ''
      echo "Using local aw-client from activitywatch_src/"
    ''}
    ${lib.optionalString (aw-core == null) ''
      echo "Using local aw-core from activitywatch_src/"
    ''}
  '';

  # Don't run tests during build (no tests yet)
  doCheck = false;

  pythonImportsCheck = [
    "aw_llm_worker"
    "aw_llm_worker.models"
    "aw_llm_worker.config"
  ];

  postInstall = ''
    # Ensure the CLI script is available
    wrapProgram $out/bin/aw-sorter \
      --prefix PATH : ${lib.makeBinPath [ ]}
  '';

  meta = with lib; {
    description = "ActivityWatch LLM categorizer sidecar - enriches and classifies AW events via LLM + rules";
    homepage = "https://github.com/dtgagnon/activitywatch";
    license = licenses.mpl20;
    maintainers = [ ];
    mainProgram = "aw-sorter";
    platforms = platforms.linux ++ platforms.darwin;
  };
}
