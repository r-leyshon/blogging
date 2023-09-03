" Provided with a spotify album ID, these functions return the album art and
a ridge plot of the musical features in each album track."

library(here)
library(spotifyr)
library(ggplot2)
library(ggridges)
library(tidyr)
library(dplyr)
library(glue)
source(here("R/music-reviews/config-secrets.R"))


get_album_artwork_url = function(
    spotify_id = "6mS0ssCxtLvB0IcVP7sR66",
    api_key_path = here::here(".secrets.toml")
    ){
    # configure api secrets
    config_secrets(api_key_path)
    access_token <- spotifyr::get_spotify_access_token()
    # get album
    album = spotifyr::get_album(spotify_id)
    return(album[["images"]][["url"]][1])
    }

get_album_audio_features = function(
    spotify_id = "6mS0ssCxtLvB0IcVP7sR66",
    api_key_path = here::here(".secrets.toml")
    ){
    # configure api secrets
    config_secrets(api_key_path)
    access_token <- spotifyr::get_spotify_access_token()
    # get album
    album = spotifyr::get_album(spotify_id)
    return(album)
}


get_track_audio_features = function(
    spotify_id = "6mS0ssCxtLvB0IcVP7sR66",
    api_key_path = here::here(".secrets.toml"),
    debug = FALSE
    ){
    # configure api secrets
    config_secrets(api_key_path)
    access_token <- spotifyr::get_spotify_access_token()
    album = get_album_audio_features(spotify_id, api_key_path)
    # get artist name for title
    artist_name = album[["artists"]]$name
    # collect features for each track in album
    tracks = album[["tracks"]]
    track_ids = tracks$items$id
    track_features = data.frame()
    track_names = tracks$items$name
    i = 1
    for(id in track_ids) {
        if (debug) {
            print(glue::glue("Query track id: {id}"))
        }
        track = spotifyr::get_track_audio_features(id)
        track = cbind(track_name = track_names[i], track_order = i, track)
        track_features = rbind(track_features, track)
        i = i + 1
        }
    out = list(
        album_name = album$name,
        artist = artist_name,
        features = track_features)
    return(out)
}

viz_album_audio_features = function(
    spotify_id = "6mS0ssCxtLvB0IcVP7sR66",
    api_key_path = here::here(".secrets.toml"),
    audio_features = c("danceability", "energy", "speechiness",
                       "acousticness", "instrumentalness", "valence"),
    title_font_size = 14,
    subtitle_font_size = 10,
    title_hjust = 0.5,
    subtitle_hjust = 0.5,
    debug = FALSE
    ){
    # configure api secrets
    config_secrets(api_key_path)
    access_token <- spotifyr::get_spotify_access_token()
    album_deets = get_track_audio_features(
        spotify_id, api_key_path, debug = debug
        )
    # pivot long on features to plot
    tracks_long = tidyr::pivot_longer(
        album_deets[["features"]], cols=all_of(audio_features),
        names_to="features"
        )
    # create the plot
    plt = ggplot2::ggplot(
        tracks_long, ggplot2::aes(x = value, y = features, fill = features)
        ) +
    ggridges::geom_density_ridges(
        alpha=0.7, scale = 3, rel_min_height = 0.01
        ) + 
    ggridges::theme_ridges(grid = FALSE, center_axis_labels = TRUE) +
    ggplot2::ggtitle(
      glue::glue("{album_deets[['album_name']]} by {album_deets[['artist']]}"),
      subtitle = "A Density Ridge Plot of Audio Features.") +
    ggplot2::labs(x = "", y = "") +
    ggplot2::theme(
      legend.position = "none",
      axis.text.x = ggplot2::element_blank(),
      axis.ticks = ggplot2::element_blank(),
      panel.background = ggplot2::element_rect(fill = "black"),
      plot.background = ggplot2::element_rect(fill = "black"),
      plot.title = ggplot2::element_text(
        color = "white", family = "Arial Rounded MT Bold",
        size = title_font_size, hjust = title_hjust
        ),
      plot.subtitle = ggplot2::element_text(
        color = "white", family = "Arial Rounded MT Bold",
        size = subtitle_font_size, hjust = subtitle_hjust
        ),
      axis.text.y = ggplot2::element_text(
        color = "white", family = "Arial Rounded MT Bold"
        ))
    print(plt)
    }


create_album_audio_summary_table = function(
    spotify_id = "6mS0ssCxtLvB0IcVP7sR66",
    api_key_path = here::here(".secrets.toml"),
    audio_features = c(
        "danceability", "energy", "speechiness",
        "acousticness", "instrumentalness", "valence")
        ){
            album_deets = get_track_audio_features(spotify_id, api_key_path)
            track_features = dplyr::select(
                album_deets[["features"]],
                all_of(c("track_name", audio_features))
                )
                return(track_features)
                }
