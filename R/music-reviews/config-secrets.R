library(configr)
config_secrets <- function(toml_path = NULL){
  # read toml
  creds <- read.config(toml_path)
  # set to system variables
  Sys.setenv(SPOTIFY_CLIENT_ID = creds$spotify$client_id)
  Sys.setenv(SPOTIFY_CLIENT_SECRET = creds$spotify$client_secret)
}
