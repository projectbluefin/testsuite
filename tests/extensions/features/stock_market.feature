@extensions_suite @stock_market
Feature: Stock Market desktop watchlist
  The configured watchlist and desktop card remain usable independently of
  whether Yahoo Finance returns live quotes. Price success and cache fallback
  require the deterministic HTTPS fixture lane tracked in issue #909.

  Background:
    Given Hive extension "stock-market" is installed
    And Stock Market is disabled for configuration
    And the Stock Market language setting is "en"
    And the Stock Market position settings are left 24 and top 48

  Scenario: The configured watchlist renders only the selected symbols in order
    Given the Stock Market watchlist contains these symbols:
      | symbol  |
      | BTC-USD |
      | ^GSPC   |
      | MBB.VN  |
    When I enable the selected Hive extension
    Then exactly one Stock Market card is mapped on the desktop
    And Stock Market displays these labels:
      | style_class  | text              |
      | stocks-title | FINANCIAL MARKETS |
    And Stock Market shows exactly 3 watchlist rows in this order:
      | symbol  |
      | BTC-USD |
      | ^GSPC   |
      | MBB.VN  |

  Scenario: The language setting switches English and Vietnamese rendered labels
    Given the Stock Market watchlist is empty
    When I enable the selected Hive extension
    Then Stock Market displays these labels:
      | style_class     | text                                     |
      | stocks-title    | FINANCIAL MARKETS                        |
      | stocks-subtitle | Yahoo Finance                            |
      | stocks-subtitle | Updated: --:--                           |
      | stocks-subtitle | No price data. Add symbols in Preferences. |
    When the Stock Market language setting is "vi"
    Then exactly one Stock Market card is mapped on the desktop
    And Stock Market displays these labels:
      | style_class     | text                                            |
      | stocks-title    | THỊ TRƯỜNG TÀI CHÍNH                            |
      | stocks-subtitle | Yahoo Finance                                   |
      | stocks-subtitle | Cập nhật: --:--                                  |
      | stocks-subtitle | Chưa có dữ liệu giá. Thêm mã trong Tùy chọn.      |
    When the Stock Market language setting is "en"
    Then Stock Market displays these labels:
      | style_class     | text                                      |
      | stocks-title    | FINANCIAL MARKETS                         |
      | stocks-subtitle | Yahoo Finance                             |
      | stocks-subtitle | Updated: --:--                            |
      | stocks-subtitle | No price data. Add symbols in Preferences. |

  Scenario: Position settings move the rendered card without restarting it
    Given the Stock Market watchlist is empty
    When I enable the selected Hive extension
    Then exactly one Stock Market card is mapped on the desktop
    And the Stock Market card is left 24 and top 48 from the primary monitor origin
    When the Stock Market position settings are left 72 and top 96
    Then the Stock Market card is left 72 and top 96 from the primary monitor origin
    And exactly one Stock Market card is mapped on the desktop
    And Stock Market displays these labels:
      | style_class  | text              |
      | stocks-title | FINANCIAL MARKETS |

  Scenario: Disable removes the card and reenable restores exactly one card
    Given the Stock Market watchlist is empty
    And the Stock Market language setting is "vi"
    When I enable the selected Hive extension
    Then exactly one Stock Market card is mapped on the desktop
    And Stock Market displays these labels:
      | style_class  | text                 |
      | stocks-title | THỊ TRƯỜNG TÀI CHÍNH |
    When I disable the selected Hive extension
    Then no Stock Market card remains in the Shell actor tree
    When I enable the selected Hive extension
    Then exactly one Stock Market card is mapped on the desktop
    And the Stock Market card is left 24 and top 48 from the primary monitor origin
    And Stock Market displays these labels:
      | style_class     | text                                       |
      | stocks-title    | THỊ TRƯỜNG TÀI CHÍNH                       |
      | stocks-subtitle | Yahoo Finance                              |
      | stocks-subtitle | Cập nhật: --:--                             |
      | stocks-subtitle | Chưa có dữ liệu giá. Thêm mã trong Tùy chọn. |

  Scenario: Stock Market helper nonzero-exit path surfaces a real warning and cleans up on disable
    Given the Stock Market Python helper is replaced with a nonzero-exit stub
    And the Stock Market watchlist contains these symbols:
      | symbol  |
      | BTC-USD |
    When I enable the selected Hive extension
    Then exactly one Stock Market card is mapped on the desktop
    And Stock Market displays these labels:
      | style_class     | text                                                   |
      | stocks-title    | FINANCIAL MARKETS                                     |
      | stocks-error    | Could not update prices. Will retry automatically.    |
    And no Stock Market helper or curl child process remains for the candidate
    When I disable the selected Hive extension
    Then no Stock Market card remains in the Shell actor tree
    And no Stock Market helper or curl child process remains for the candidate
